import os
import time
import asyncio
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
from app.whatsapp import (
    parse_incoming_message,
    download_media,
    send_text_message,
    send_messenger_message,
    download_messenger_media,
    parse_messenger_message
)


app = FastAPI(
    title="RUTAQ API",
    description="Asistente IA del MRE para orientación de apostilla y legalización",
    version="1.0.0"
)

# Historial en memoria
conversation_history: dict[str, list] = {}

# Buffer para agrupar imágenes del mismo usuario
image_buffer: dict[str, list] = {}
image_buffer_time: dict[str, float] = {}
BUFFER_SECONDS = 8

# Palabras a ignorar
PALABRAS_IGNORAR = {
    "ok", "okay", "bien", "gracias", "si", "sí", "no", "ya",
    "dale", "listo", "claro", "entendido", "perfecto", "bueno",
    "hm", "ah", "aja", "ajá"
}


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


async def procesar_imagenes_pendientes(sender: str, imagenes: list, opcion: str, history: list) -> str:
    """Procesa imágenes según la opción elegida por el usuario"""
    if opcion == "1":
        await send_text_message(sender, "🔍 Analizando frente y reverso...\n⏳ Dame un momento.")
        response_frente = await process_message("image", imagenes[0], filename="frente.jpg", conversation_history=history)
        if len(imagenes) >= 2:
            response_reverso = await process_message("image", imagenes[1], filename="reverso.jpg", conversation_history=history)
            return (
                "📄 *ANÁLISIS COMPLETO DEL DOCUMENTO*\n\n"
                "🔼 *Cara frontal:*\n" + response_frente +
                "\n\n━━━━━━━━━━━━━━━\n"
                "🔽 *Cara posterior:*\n" + response_reverso
            )
        return response_frente

    elif opcion == "2":
        await send_text_message(sender, f"📋 Analizaré {len(imagenes)} documentos por separado...")
        responses = []
        for i, img in enumerate(imagenes, 1):
            r = await process_message("image", img, filename=f"documento_{i}.jpg", conversation_history=history)
            responses.append(f"📄 *Documento {i}:*\n{r}")
        return "\n\n━━━━━━━━━━━━━━━\n\n".join(responses)

    elif opcion == "3":
        await send_text_message(sender, "📑 Analizando expediente...\n⏳ Dame un momento.")
        r = await process_message("image", imagenes[0], filename="expediente.jpg", conversation_history=history)
        return f"📑 Analicé la página principal ({len(imagenes)} páginas recibidas).\n\n{r}"

    return "No entendí tu opción. Responde 1, 2 o 3."


@app.post("/webhook")
async def receive_message(request: Request):
    sender = None
    try:
        body = await request.body()
        params = parse_qs(body.decode("utf-8"))
        payload = {k: v[0] for k, v in params.items()}

        print(f"📨 Webhook Twilio: {payload}")

        message = parse_incoming_message(payload)
        if not message:
            return PlainTextResponse("")

        sender = message["from"]
        msg_type = message["type"]

        print(f"📱 Mensaje de {sender} | Tipo: {msg_type}")

        history = conversation_history.get(sender, [])
        response = None

        # ── TEXTO ──────────────────────────────────────────────
        if msg_type == "text":
            user_text = message["text"].strip()

            # Verificar si es respuesta a pregunta de imágenes (1, 2 o 3)
            if user_text in ["1", "2", "3"] and f"{sender}_pending" in image_buffer:
                imagenes_pending = image_buffer.pop(f"{sender}_pending")
                response = await procesar_imagenes_pendientes(
                    sender, imagenes_pending, user_text, history
                )
                history.append({"role": "assistant", "content": response[:500]})
                conversation_history[sender] = history[-10:]

            # Ignorar mensajes vacíos o confirmaciones cortas
            elif not user_text or user_text.lower() in PALABRAS_IGNORAR:
                return PlainTextResponse("")

            else:
                response = await process_message("text", user_text, conversation_history=history)
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": response})
                conversation_history[sender] = history[-10:]

        # ── UBICACIÓN ──────────────────────────────────────────
        elif msg_type == "location":
            lat = message.get("latitude")
            lon = message.get("longitude")
            response = await process_message(
                "text",
                f"[El usuario compartió su ubicación GPS: lat={lat}, lon={lon}. "
                f"Dile cuál es la oficina del MRE, RENIEC, SUNEDU o Colegio de Notarios "
                f"más cercana a esa ubicación en Lima Perú.]",
                conversation_history=history
            )
            history.append({"role": "user", "content": f"Mi ubicación: lat={lat}, lon={lon}"})
            history.append({"role": "assistant", "content": response})
            conversation_history[sender] = history[-10:]

        # ── IMAGEN (con buffer) ────────────────────────────────
        elif msg_type == "image":
            now = time.time()

            # Inicializar buffer si es nuevo o expiró
            if sender not in image_buffer_time or \
               (now - image_buffer_time[sender]) > BUFFER_SECONDS * 2:
                image_buffer[sender] = []
                image_buffer_time[sender] = now

            # Descargar y agregar al buffer
            media_bytes = await download_media(message["media_url"])
            image_buffer[sender].append(media_bytes)
            image_buffer_time[sender] = time.time()
            print(f"📸 Imagen {len(image_buffer[sender])} en buffer de {sender}")

            # Esperar por más imágenes
            await asyncio.sleep(BUFFER_SECONDS)

            # Solo procesar si no llegó otra imagen después
            tiempo_desde_ultima = time.time() - image_buffer_time[sender]
            if tiempo_desde_ultima < BUFFER_SECONDS - 1:
                return PlainTextResponse("")

            imagenes = image_buffer.pop(sender, [])
            image_buffer_time.pop(sender, None)

            if not imagenes:
                return PlainTextResponse("")

            print(f"🖼️ Procesando {len(imagenes)} imagen(es) de {sender}")

            if len(imagenes) > 1:
                # Guardar y preguntar al usuario qué tipo de imágenes son
                image_buffer[f"{sender}_pending"] = imagenes
                response = (
                    f"📎 Recibí *{len(imagenes)} imágenes*.\n\n"
                    f"Para analizarlas correctamente, dime:\n\n"
                    f"1️⃣ Son *frente y reverso* del mismo documento\n"
                    f"2️⃣ Son *documentos diferentes*\n"
                    f"3️⃣ Son *páginas del mismo expediente*\n\n"
                    f"Responde con el número *1*, *2* o *3*."
                )
            else:
                await send_text_message(sender, "📄 Analizando tu documento...\n⏳ Dame un momento.")
                response = await process_message(
                    "image", imagenes[0],
                    filename="documento.jpg",
                    conversation_history=history
                )

            history.append({"role": "assistant", "content": response[:500]})
            conversation_history[sender] = history[-10:]

        # ── AUDIO ──────────────────────────────────────────────
        elif msg_type == "audio":
            await send_text_message(sender, "🎙️ Escuchando tu nota de voz...\n⏳ Dame un segundo.")
            media_bytes = await download_media(message["media_url"])
            response = await process_message(
                "audio", media_bytes,
                filename=message["filename"],
                conversation_history=history
            )
            history.append({"role": "assistant", "content": response[:500]})
            conversation_history[sender] = history[-10:]

        # ── BIENVENIDA ─────────────────────────────────────────
        else:
            response = await process_message("unknown", "", conversation_history=history)

        # Enviar respuesta
        if response:
            await send_text_message(sender, response)
            print(f"✅ Respuesta enviada a {sender}")

        return PlainTextResponse("")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        if sender:
            try:
                await send_text_message(
                    sender,
                    "⚠️ Tuve un problema procesando tu mensaje.\n"
                    "Por favor intenta de nuevo o escríbeme qué documento necesitas apostillar."
                )
            except Exception:
                pass
        return PlainTextResponse("")


# ── MESSENGER WEBHOOK ──────────────────────────────────────
@app.get("/webhook/messenger")
async def verify_messenger(request: Request):
    """Verificación del webhook de Messenger"""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    verify_token = os.getenv("MESSENGER_VERIFY_TOKEN", "rutaq2026messenger")

    if mode == "subscribe" and token == verify_token:
        print("✅ Messenger webhook verificado")
        return PlainTextResponse(challenge)
    return PlainTextResponse("Error", status_code=403)


@app.post("/webhook/messenger")
async def receive_messenger(request: Request):
    """Recibe mensajes de Messenger y los procesa con RUTAQ"""
    sender = None
    try:
        payload = await request.json()
        print(f"📨 Messenger webhook: {payload}")

        message = parse_messenger_message(payload)
        if not message:
            return {"status": "ok"}

        sender = message["from"]
        msg_type = message["type"]
        print(f"💬 Messenger de {sender} | Tipo: {msg_type}")

        history = conversation_history.get(f"messenger_{sender}", [])
        response = None

        if msg_type == "text":
            user_text = message["text"].strip()
            if not user_text or user_text.lower() in PALABRAS_IGNORAR:
                return {"status": "ok"}
            response = await process_message("text", user_text, conversation_history=history)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response})
            conversation_history[f"messenger_{sender}"] = history[-10:]

        elif msg_type == "image":
            await send_messenger_message(sender, "📄 Analizando tu documento...\n⏳ Dame un momento.")
            media_bytes = await download_messenger_media(message["media_url"])
            response = await process_message("image", media_bytes, filename="documento.jpg", conversation_history=history)
            history.append({"role": "assistant", "content": response[:500]})
            conversation_history[f"messenger_{sender}"] = history[-10:]

        elif msg_type == "audio":
            await send_messenger_message(sender, "🎙️ Escuchando tu nota de voz...\n⏳ Dame un segundo.")
            media_bytes = await download_messenger_media(message["media_url"])
            response = await process_message("audio", media_bytes, filename="audio.mp4", conversation_history=history)
            history.append({"role": "assistant", "content": response[:500]})
            conversation_history[f"messenger_{sender}"] = history[-10:]

        else:
            response = await process_message("unknown", "", conversation_history=history)

        if response:
            await send_messenger_message(sender, response)
            print(f"✅ Messenger respuesta enviada a {sender}")

        return {"status": "ok"}

    except Exception as e:
        print(f"❌ Error Messenger: {e}")
        import traceback
        traceback.print_exc()
        if sender:
            try:
                await send_messenger_message(sender, "⚠️ Tuve un problema. Por favor intenta de nuevo.")
            except Exception:
                pass
        return {"status": "ok"}
