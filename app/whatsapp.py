import os
import httpx

WHATSAPP_API_URL = "https://graph.facebook.com/v20.0"
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")


async def send_text_message(to: str, message: str) -> dict:
    """Envía mensaje de texto por WhatsApp"""
    url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": message, "preview_url": False}
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        return response.json()


async def send_typing_indicator(to: str):
    """Muestra 'escribiendo...' mientras RUTAQ procesa"""
    url = f"{WHATSAPP_API_URL}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": to  # workaround para typing
    }
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers=headers)


async def download_media(media_id: str) -> bytes:
    """Descarga imagen o audio enviado por el usuario"""
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    
    # 1. Obtener URL del archivo
    async with httpx.AsyncClient() as client:
        meta = await client.get(
            f"{WHATSAPP_API_URL}/{media_id}",
            headers=headers
        )
        media_url = meta.json().get("url")
        
        # 2. Descargar el archivo
        file_response = await client.get(media_url, headers=headers)
        return file_response.content


def parse_incoming_message(payload: dict) -> dict | None:
    """
    Extrae la información relevante del webhook de Meta.
    Retorna: {from, type, content, message_id} o None si no es mensaje
    """
    try:
        entry = payload["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        
        if "messages" not in value:
            return None
        
        message = value["messages"][0]
        sender = message["from"]
        msg_type = message["type"]
        message_id = message["id"]
        
        result = {
            "from": sender,
            "type": msg_type,
            "message_id": message_id,
            "media_id": None,
            "text": None,
            "filename": None
        }
        
        if msg_type == "text":
            result["text"] = message["text"]["body"]
        
        elif msg_type == "image":
            result["media_id"] = message["image"]["id"]
            result["filename"] = "documento.jpg"
        
        elif msg_type == "audio":
            result["media_id"] = message["audio"]["id"]
            result["filename"] = "audio.ogg"
        
        elif msg_type == "document":
            result["media_id"] = message["document"]["id"]
            result["filename"] = message["document"].get("filename", "documento.pdf")
            result["type"] = "image"  # tratar PDF como imagen para análisis
        
        return result
    
    except (KeyError, IndexError):
        return None
