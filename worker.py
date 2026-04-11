import os
import httpx
from groq import Groq
from nl_to_sql.pipeline import run_pipeline

WHATSAPP_TOKEN = os.environ["WHATSAPP_TOKEN"]
WHATSAPP_PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

groq_client = Groq(api_key=GROQ_API_KEY)


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
        client.post(url, headers=headers, json=payload)


def process_query(from_number: str, msg_type: str, content: str):
    try:
        if msg_type == "audio":
            print(f"[WORKER] Descargando audio {content}")
            audio_bytes = download_audio(content)
            print(f"[WORKER] Transcribiendo audio")
            query_text = transcribe_audio(audio_bytes)
            print(f"[WORKER] Transcripción: {query_text}")
        else:
            query_text = content

        print(f"[WORKER] Procesando query: {query_text}")
        response = run_pipeline(query_text)
        send_whatsapp_message(from_number, response)

    except Exception as e:
        print(f"[WORKER ERROR] {e}")
        send_whatsapp_message(from_number, "Ocurrió un error procesando tu consulta. Intentá de nuevo.")