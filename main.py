from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
import json
import redis
import uuid
from rq import Queue

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
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        if "messages" not in entry:
            return {"status": "ignored"}
        
        msg = entry["messages"][0]
        from_number = msg["from"]
        msg_type = msg["type"]

        if msg_type == "text":
            text = msg["text"]["body"]
            q.enqueue("worker.process_query", from_number, "text", text)

        elif msg_type == "audio":
            audio_id = msg["audio"]["id"]
            q.enqueue("worker.process_query", from_number, "audio", audio_id)

        else:
            return {"status": "ignored"}

    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

    return {"status": "ok"}