import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from urllib.parse import parse_qs

from app.agent import process_message
from app.whatsapp import (
    parse_incoming_message,
    download_media,
    send_text_message
)

app = FastAPI(
    title="RUTAQ API",
    description="Asistente IA del MRE para orientación de apostilla y legalización",
    version="1.0.0"
)

# Historial en memoria
conversation_history: dict[str, list] = {}


@app.get("/")
async def root():
    return {
        "name": "RUTAQ",
        "description": "Asistente IA del MRE - Apostilla y Legalización",
        "status": "activo",
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def receive_message(request: Request):
    """
    Recibe mensajes de WhatsApp via Twilio y los procesa con RUTAQ.
    """
    try:
        # Twilio envía form-data
        body = await request.body()
        params = parse_qs(body.decode("utf-8"))
        payload = {k: v[0] for k, v in params.items()}
        
        print(f"📨 Webhook Twilio: {payload}")

        message = parse_incoming_message(payload)
        if not message:
            return PlainTextResponse("ok")

        sender = message["from"]
        msg_type = message["type"]

        print(f"📱 Mensaje de {sender} | Tipo: {msg_type}")

        history = conversation_history.get(sender, [])

        if msg_type == "text":
            user_text = message["text"]
            if not user_text.strip():
                return PlainTextResponse("ok")
            response = await process_message("text", user_text, conversation_history=history)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response})
            conversation_history[sender] = history[-10:]

        elif msg_type in ("image", "audio"):
            media_bytes = await download_media(message["media_url"])
            response = await process_message(
                msg_type,
                media_bytes,
                filename=message["filename"],
                conversation_history=history
            )
            history.append({"role": "assistant", "content": response})
            conversation_history[sender] = history[-10:]

        else:
            response = await process_message("unknown", "", conversation_history=history)

        await send_text_message(sender, response)
        print(f"✅ Respuesta enviada a {sender}")

        return PlainTextResponse("ok")

    except Exception as e:
        print(f"❌ Error: {e}")
        return PlainTextResponse("ok")
