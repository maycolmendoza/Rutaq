import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
import asyncio

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

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "rutaq2026")

# Historial simple en memoria (en producción: PostgreSQL)
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


@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Verificación del webhook por Meta.
    Meta envía un GET con hub.challenge para confirmar que el servidor existe.
    """
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print(f"✅ Webhook verificado correctamente")
        return PlainTextResponse(content=challenge)
    
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/webhook")
async def receive_message(request: Request):
    """
    Recibe mensajes de WhatsApp y los procesa con RUTAQ.
    Maneja: texto, imágenes, audio/voz, documentos PDF.
    """
    try:
        payload = await request.json()
        print(f"📨 Webhook recibido: {payload}")
        
        # Parsear el mensaje entrante
        message = parse_incoming_message(payload)
        if not message:
            return {"status": "no_message"}
        
        sender = message["from"]
        msg_type = message["type"]
        
        print(f"📱 Mensaje de {sender} | Tipo: {msg_type}")
        
        # Obtener historial de conversación
        history = conversation_history.get(sender, [])
        
        # Procesar según tipo de mensaje
        if msg_type == "text":
            user_text = message["text"]
            response = await process_message("text", user_text, conversation_history=history)
            
            # Guardar en historial
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response})
            conversation_history[sender] = history[-10:]  # últimos 5 turnos
        
        elif msg_type in ("image", "audio"):
            # Descargar el archivo multimedia
            media_bytes = await download_media(message["media_id"])
            response = await process_message(
                msg_type,
                media_bytes,
                filename=message["filename"],
                conversation_history=history
            )
            history.append({"role": "assistant", "content": response})
            conversation_history[sender] = history[-10:]
        
        else:
            # Mensaje de bienvenida para tipos no soportados
            response = await process_message("unknown", "", conversation_history=history)
        
        # Enviar respuesta por WhatsApp
        await send_text_message(sender, response)
        print(f"✅ Respuesta enviada a {sender}")
        
        return {"status": "ok"}
    
    except Exception as e:
        print(f"❌ Error procesando mensaje: {e}")
        # Nunca dejar al usuario sin respuesta
        try:
            if message and sender:
                await send_text_message(
                    sender,
                    "Disculpa, tuve un problema procesando tu mensaje. "
                    "Por favor escríbeme de nuevo o llama al MRE: Jr. Lampa 545."
                )
        except:
            pass
        return {"status": "error", "detail": str(e)}
