import json
import logging
import os

import httpx
from groq import Groq

# Configurar logging ANTES de importar pipeline. Sin esto, los logger.info
# del pipeline no salen a stdout cuando el worker corre vía `rq worker`.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from nl_to_sql.pipeline import run_pipeline

logger = logging.getLogger(__name__)

WHATSAPP_TOKEN = os.environ["WHATSAPP_TOKEN"]
WHATSAPP_PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

groq_client = Groq(api_key=GROQ_API_KEY)

HISTORY_TTL = int(os.environ.get("HISTORY_TTL", "1800"))  # segundos; default 30 min
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "5"))  # últimos N intercambios


def get_history(r, user_id: str) -> list:
    """
    Historial estructurado: lista de turnos
      [{ user_message, intent, sql, row_count, result_summary }, ...]

    Formato nuevo desde el paso 2. La limpieza de Redis se asume ya hecha,
    así que no hacemos parseo defensivo del formato viejo.
    """
    key = f"history:{user_id}"
    data = r.get(key)
    if not data:
        return []
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        logger.warning("[HISTORY] JSON corrupto en %s — descartando", key)
        return []


def save_history(r, user_id: str, history: list):
    key = f"history:{user_id}"
    r.setex(key, HISTORY_TTL, json.dumps(history, ensure_ascii=False))


def update_history(r, user_id: str, history_entry: dict):
    """
    Agrega un turno estructurado al historial y mantiene solo los últimos
    MAX_HISTORY_TURNS. Ya no guardamos el texto formateado con emojis.
    """
    history = get_history(r, user_id)
    history.append(history_entry)
    if len(history) > MAX_HISTORY_TURNS:
        history = history[-MAX_HISTORY_TURNS:]
    save_history(r, user_id, history)


def download_audio(audio_id: str) -> bytes:
    url = f"https://graph.facebook.com/v20.0/{audio_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    with httpx.Client() as client:
        meta = client.get(url, headers=headers).json()
        audio_url = meta["url"]
        response = client.get(audio_url, headers=headers)
        return response.content


def transcribe_audio(audio_bytes: bytes) -> str:
    transcription = groq_client.audio.transcriptions.create(
        file=("audio.ogg", audio_bytes, "audio/ogg"),
        model="whisper-large-v3",
        language="es",
    )
    return transcription.text


def send_whatsapp_message(to: str, text: str):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    with httpx.Client() as client:
        response = client.post(url, headers=headers, json=payload)
        logger.info("[SEND] Status: %s | Response: %s", response.status_code, response.text)


def process_query(from_number: str, msg_type: str, content: str):
    import redis
    r = redis.from_url(os.environ["REDIS_URL"])

    try:
        if msg_type == "audio":
            send_whatsapp_message(from_number, "🎙️ Escuchando tu mensaje...")
            logger.info("[WORKER] Descargando audio %s", content)
            audio_bytes = download_audio(content)
            logger.info("[WORKER] Transcribiendo audio")
            query_text = transcribe_audio(audio_bytes)
            logger.info("[WORKER] Transcripción: %s", query_text)
            send_whatsapp_message(from_number, f'🎙️ _Escuché: "{query_text}"_')
        else:
            query_text = content

        logger.info("[WORKER] Procesando query: %s", query_text)
        history = get_history(r, from_number)
        logger.info("[WORKER] Historial: %d turnos", len(history))

        response_text, history_entry = run_pipeline(query_text, history)
        update_history(r, from_number, history_entry)
        send_whatsapp_message(from_number, response_text)

    except Exception as exc:
        logger.exception("[WORKER ERROR] %s", exc)
        send_whatsapp_message(
            from_number,
            "Ocurrió un error procesando tu consulta. Intentá de nuevo.",
        )
