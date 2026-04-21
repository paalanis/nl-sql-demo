import os
import json
import httpx
from groq import Groq
from nl_to_sql.pipeline import run_pipeline

WHATSAPP_TOKEN = os.environ["WHATSAPP_TOKEN"]
WHATSAPP_PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

groq_client = Groq(api_key=GROQ_API_KEY)

HISTORY_TTL = 1800  # 30 minutos
MAX_HISTORY_TURNS = 5  # últimos 5 intercambios


def get_history(r, user_id: str) -> list:
    key = f"history:{user_id}"
    data = r.get(key)
    if data:
        return json.loads(data)
    return []


def save_history(r, user_id: str, history: list):
    key = f"history:{user_id}"
    r.setex(key, HISTORY_TTL, json.dumps(history))


def update_history(r, user_id: str, query_text: str, response_text: str):
    history = get_history(r, user_id)
    history.append({"role": "user", "content": query_text})
    history.append({"role": "assistant", "content": response_text})
    # Mantener solo los últimos MAX_HISTORY_TURNS intercambios
    if len(history) > MAX_HISTORY_TURNS * 2:
        history = history[-(MAX_HISTORY_TURNS * 2):]
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
        language="es"
    )
    return transcription.text


def send_whatsapp_message(to: str, text: str):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    with httpx.Client() as client:
        response = client.post(url, headers=headers, json=payload)
        print(f"[SEND] Status: {response.status_code} | Response: {response.text}")


def process_query(from_number: str, msg_type: str, content: str):
    import redis
    r = redis.from_url(os.environ["REDIS_URL"])

    try:
        if msg_type == "audio":
            send_whatsapp_message(from_number, "🎙️ Escuchando tu mensaje...")
            print(f"[WORKER] Descargando audio {content}")
            audio_bytes = download_audio(content)
            print(f"[WORKER] Transcribiendo audio")
            query_text = transcribe_audio(audio_bytes)
            print(f"[WORKER] Transcripción: {query_text}")
            send_whatsapp_message(from_number, f"🎙️ _Escuché: \"{query_text}\"_")
        else:
            query_text = content

        print(f"[WORKER] Procesando query: {query_text}")
        history = get_history(r, from_number)
        print(f"[WORKER] Historial: {len(history)} mensajes")

        response = run_pipeline(query_text, history)
        update_history(r, from_number, query_text, response)
        send_whatsapp_message(from_number, response)

    except Exception as e:
        print(f"[WORKER ERROR] {e}")
        send_whatsapp_message(from_number, "Ocurrió un error procesando tu consulta. Intentá de nuevo.")