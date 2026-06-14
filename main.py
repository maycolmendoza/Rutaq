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
    "hm", "ah", "aja", "ajá", "ok"
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


@app.post("/webhook")
async def receive_message(request: Request):
    """
    Recibe mensajes de WhatsApp via Twilio y los procesa con RUTAQ.
    Maneja: texto, imágenes (con buffer), audio, ubicación.
    """
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
            
            # Detectar respuesta a la pregunta de imágenes
if user_text.strip() in ["1", "2", "3"] and \
   f"{sender}_pending" in image_buffer:
    
    imagenes_pending = image_buffer.pop(f"{sender}_pending")
    opcion = user_text.strip()
    
    if opcion == "1":
        # Frente y reverso — analizar juntos como un solo documento
        await send_text_message(sender,
            "🔍 Analizando frente y reverso de tu documento...\n⏳ Dame un momento."
        )
        response_frente = await process_message(
            "image", imagenes_pending[0],
            filename="frente.jpg",
            conversation_history=history
        )
        response_reverso = await process_message(
            "image", imagenes_pending[1],
            filename="reverso.jpg", 
            conversation_history=history
        )
        response = (
            "📄 *ANÁLISIS COMPLETO DEL DOCUMENTO*\n\n"
            "🔼 *Cara frontal:*\n" + response_frente +
            "\n\n━━━━━━━━━━━━━━━\n"
            "🔽 *Cara posterior:*\n" + response_reverso
        )
    
    elif opcion == "2":
        # Documentos distintos — analizar uno por uno
        await send_text_message(sender,
            f"📋 Analizaré {len(imagenes_pending)} documentos por separado..."
        )
        responses = []
        for i, img in enumerate(imagenes_pending, 1):
            r = await process_message(
                "image", img,
                filename=f"documento_{i}.jpg",
                conversation_history=history
            )
            responses.append(f"📄 *Documento {i}:*\n{r}")
        response = "\n\n━━━━━━━━━━━━━━━\n\n".join(responses)
    
    elif opcion == "3":
        # Páginas del mismo expediente — analizar la primera página principal
        await send_text_message(sender,
            "📑 Analizando el expediente completo...\n⏳ Dame un momento."
        )
        # Usar primera imagen como principal
        response = await process_message(
            "image", imagenes_pending[0],
            filename="expediente.jpg",
            conversation_history=history
        )
        response = (
            f"📑 Analicé la página principal de tu expediente "
            f"({len(imagenes_pending)} páginas recibidas).\n\n" + response
        )
            # Ignorar mensajes vacíos o confirmaciones cortas
            if not user_text or user_text.lower() in PALABRAS_IGNORAR:
                return PlainTextResponse("")

            # Detectar si comparte ubicación por texto (ej: "estoy en Miraflores")
            response = await process_message(
                "text", user_text,
                conversation_history=history
            )
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response})
            conversation_history[sender] = history[-10:]

        # ── UBICACIÓN ──────────────────────────────────────────
        elif msg_type == "location":
            lat = message.get("latitude")
            lon = message.get("longitude")
            location_text = f"Mi ubicación es latitud {lat}, longitud {lon}"
            response = await process_message(
                "text",
                f"[El usuario compartió su ubicación GPS: lat={lat}, lon={lon}. "
                f"Dile cuál es la oficina del MRE, RENIEC, SUNEDU o Colegio de Notarios "
                f"más cercana a esa ubicación en Lima Perú.]",
                conversation_history=history
            )
            history.append({"role": "user", "content": location_text})
            history.append({"role": "assistant", "content": response})
            conversation_history[sender] = history[-10:]

        # ── IMAGEN (con buffer para múltiples imágenes) ────────
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
            print(f"📸 Imagen {len(image_buffer[sender])} agregada al buffer de {sender}")

            # Esperar por más imágenes
            await asyncio.sleep(BUFFER_SECONDS)

            # Solo procesar si soy el último que actualizó el buffer
            tiempo_desde_ultima = time.time() - image_buffer_time[sender]
            if tiempo_desde_ultima >= BUFFER_SECONDS - 1:
                imagenes = image_buffer.pop(sender, [])
                image_buffer_time.pop(sender, None)

                if not imagenes:
                    return PlainTextResponse("")

                print(f"🖼️ Procesando {len(imagenes)} imagen(es) de {sender}")

            if len(imagenes) > 1:
    # Guardar imágenes temporalmente y preguntar
    image_buffer[f"{sender}_pending"] = imagenes
    response = (
        f"📎 Recibí *{len(imagenes)} imágenes*.\n\n"
        f"Para analizarlas correctamente, dime:\n\n"
        f"1️⃣ *Frente y reverso* del mismo documento\n"
        f"2️⃣ *Documentos diferentes* (los analizo por separado)\n"
        f"3️⃣ *Páginas del mismo expediente*\n\n"
        f"Responde con el número 1, 2 o 3."
    )
                    # Si hay reverso, analizarlo también
                    if len(imagenes) >= 2:
                        response_reverso = await process_message(
                            "image",
                            imagenes[1],
                            filename="documento_reverso.jpg",
                            conversation_history=history
                        )
                        response = response + \
                            "\n\n━━━━━━━━━━━━━━━\n" \
                            "🔄 *Análisis del reverso:*\n\n" + response_reverso
                else:
                    await send_text_message(
                        sender,
                        "📄 Analizando tu documento...\n⏳ Dame un momento."
                    )
                    response = await process_message(
                        "image",
                        imagenes[0],
                        filename="documento.jpg",
                        conversation_history=history
                    )

                history.append({"role": "assistant", "content": response[:500]})
                conversation_history[sender] = history[-10:]
            else:
                # Otra imagen llegó después, este handler no procesa
                return PlainTextResponse("")

        # ── AUDIO ──────────────────────────────────────────────
        elif msg_type == "audio":
            await send_text_message(
                sender,
                "🎙️ Escuchando tu mensaje de voz...\n⏳ Dame un segundo."
            )
            media_bytes = await download_media(message["media_url"])
            response = await process_message(
                "audio",
                media_bytes,
                filename=message["filename"],
                conversation_history=history
            )
            history.append({"role": "assistant", "content": response[:500]})
            conversation_history[sender] = history[-10:]

        # ── BIENVENIDA (primer mensaje o tipo desconocido) ─────
        else:
            response = await process_message(
                "unknown", "",
                conversation_history=history
            )

        # Enviar respuesta si hay
        if response:
            await send_text_message(sender, response)
            print(f"✅ Respuesta enviada a {sender}")

        return PlainTextResponse("")

    except Exception as e:
        print(f"❌ Error procesando mensaje: {e}")
        import traceback
        traceback.print_exc()
        # Nunca dejar al usuario sin respuesta
        if sender:
            try:
                await send_text_message(
                    sender,
                    "⚠️ Tuve un problema procesando tu mensaje. "
                    "Por favor intenta de nuevo o escríbeme qué documento "
                    "necesitas apostillar."
                )
            except Exception:
                pass
        return PlainTextResponse("")
