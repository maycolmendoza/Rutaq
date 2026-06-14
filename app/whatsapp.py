import os
import httpx
from twilio.rest import Client

# ── Whatsapp ─────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

#messenger
MESSENGER_PAGE_TOKEN = os.getenv("MESSENGER_PAGE_TOKEN")
MESSENGER_VERIFY_TOKEN = os.getenv("MESSENGER_VERIFY_TOKEN", "rutaq2026messenger")


async def send_text_message(to: str, message: str) -> dict:
    """Envía mensaje de texto por WhatsApp via Twilio"""
    try:
        msg = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{to}",
            body=message
        )
        print(f"✅ Twilio mensaje enviado: {msg.sid}")
        return {"sid": msg.sid}
    except Exception as e:
        print(f"❌ Error Twilio: {e}")
        return {"error": str(e)}


async def download_media(media_url: str) -> bytes:
    """Descarga imagen o audio enviado por el usuario - sigue redirects de Twilio"""
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(media_url, auth=auth)
        print(f"📥 Media descargada: {len(response.content)} bytes, content-type: {response.headers.get('content-type')}")
        return response.content


def parse_incoming_message(payload: dict) -> dict | None:
    """
    Extrae información del webhook de Twilio.
    Twilio envía form-data, no JSON.
    """
    try:
        sender = payload.get("From", "").replace("whatsapp:", "")
        msg_type = "text"
        
        if not sender:
            return None

        result = {
            "from": sender,
            "type": "text",
            "message_id": payload.get("MessageSid", ""),
            "media_id": None,
            "text": payload.get("Body", ""),
            "filename": None,
            "media_url": None
        }

        # Detectar si tiene media (imagen o audio)
        num_media = int(payload.get("NumMedia", 0))
        if num_media > 0:
            media_url = payload.get("MediaUrl0", "")
            media_type = payload.get("MediaContentType0", "")
            result["media_url"] = media_url

            if "image" in media_type or "pdf" in media_type:
                result["type"] = "image"
                result["filename"] = "documento.jpg"
            elif "audio" in media_type or "ogg" in media_type:
                result["type"] = "audio"
                result["filename"] = "audio.ogg"

        return result

    except Exception as e:
        print(f"❌ Error parseando mensaje Twilio: {e}")
        return None


async def send_messenger_message(recipient_id: str, message: str) -> dict:
    """Envía mensaje por Messenger"""
    url = f"https://graph.facebook.com/v20.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message},
        "messaging_type": "RESPONSE"
    }
    headers = {"Authorization": f"Bearer {MESSENGER_PAGE_TOKEN}"}
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=headers)
        print(f"📤 Messenger enviado: {r.status_code}")
        return r.json()

async def download_messenger_media(url: str) -> bytes:
    """Descarga imagen enviada por Messenger"""
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        return r.content

def parse_messenger_message(payload: dict) -> dict | None:
    """Parsea webhook de Messenger"""
    try:
        entry = payload["entry"][0]
        messaging = entry["messaging"][0]
        sender_id = messaging["sender"]["id"]
        
        result = {
            "from": sender_id,
            "type": "text",
            "text": "",
            "media_url": None,
            "filename": None,
            "message_id": messaging.get("message", {}).get("mid", "")
        }

        msg = messaging.get("message", {})

        if "text" in msg:
            result["type"] = "text"
            result["text"] = msg["text"]

        elif "attachments" in msg:
            att = msg["attachments"][0]
            att_type = att.get("type", "")
            att_url = att.get("payload", {}).get("url", "")
            result["media_url"] = att_url

            if att_type == "image":
                result["type"] = "image"
                result["filename"] = "documento.jpg"
            elif att_type == "audio":
                result["type"] = "audio"
                result["filename"] = "audio.mp4"

        return result
    except Exception as e:
        print(f"❌ Error parseando Messenger: {e}")
        return None
