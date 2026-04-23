from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
import redis
from rq import Queue
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

r = redis.from_url(os.environ["REDIS_URL"])
q = Queue(connection=r)

VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]

@app.get("/webhook")
async def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    logger.info(f"[WEBHOOK] Payload recibido: {data}")
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        logger.info(f"[WEBHOOK] Entry: {entry}")
        if "messages" not in entry:
            return {"status": "ignored"}

        msg = entry["messages"][0]
        from_number = msg["from"]
        msg_type = msg["type"]
        logger.info(f"[WEBHOOK] Mensaje de {from_number}, tipo: {msg_type}")

        if msg_type == "text":
            text = msg["text"]["body"]
            job = q.enqueue("worker.process_query", from_number, "text", text)
            logger.info(f"[WEBHOOK] Job enqueued: {job.id}")

        elif msg_type == "audio":
            audio_id = msg["audio"]["id"]
            job = q.enqueue("worker.process_query", from_number, "audio", audio_id)
            logger.info(f"[WEBHOOK] Job enqueued: {job.id}")

        else:
            logger.info(f"[WEBHOOK] Tipo ignorado: {msg_type}")

    except Exception as e:
        logger.error(f"[WEBHOOK ERROR] {e}", exc_info=True)

    return {"status": "ok"}

@app.get("/debug/db-ping")
async def db_ping():
    import socket, os, time
    start = time.time()
    try:
        socket.create_connection(
            (os.environ["DB_HOST"], int(os.environ.get("DB_PORT", 3306))),
            timeout=5,
        )
        return {"ok": True, "elapsed": round(time.time() - start, 2)}
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed": round(time.time() - start, 2)}