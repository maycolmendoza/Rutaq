import os
import json
import base64
import httpx
from groq import Groq
import google.generativeai as genai
from pathlib import Path

# ── Clientes ──────────────────────────────────────────────
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ── Datos MRE ─────────────────────────────────────────────
DATA_PATH = Path(__file__).parent.parent / "data" / "cadena_mre.json"
with open(DATA_PATH, "r", encoding="utf-8") as f:
    MRE_DATA = json.load(f)

# ── System prompt principal ───────────────────────────────
SYSTEM_PROMPT = f"""
Eres RUTAQ, un asistente digital del Ministerio de Relaciones Exteriores del Perú.
Tu nombre significa "el que encuentra el camino" en quechua.

Tu misión es ayudar a ciudadanos peruanos y extranjeros a conocer los pasos exactos 
para apostillar o legalizar sus documentos ANTES de ir al MRE, evitando rechazos en ventanilla.

DATOS OFICIALES DEL MRE QUE DEBES USAR:
{json.dumps(MRE_DATA, ensure_ascii=False, indent=2)}

REGLAS CRÍTICAS:
1. Responde SIEMPRE en el idioma del usuario (español o quechua)
2. USA SOLO los datos del MRE proporcionados arriba - nunca inventes información
3. Sé claro y simple - NUNCA uses términos técnicos como "cadena de certificación" 
   En su lugar di: "los pasos que necesitas completar antes de ir al MRE"
4. Siempre incluye: pasos numerados, tiempos estimados, costos en soles, direcciones exactas
5. Si el documento tiene GRATUIDAD para peruanos, menciónalo claramente
6. Resalta con ⚠️ los errores más frecuentes para ese tipo de documento
7. Al final SIEMPRE pregunta: "¿Quieres que te genere un checklist para llevar?"
8. Si el usuario habla en quechua, responde en quechua con traducción al español

FORMATO DE RESPUESTA:
📄 *Tipo de documento detectado:* [nombre]
⏱️ *Tiempo total estimado:* [X días hábiles]
💰 *Costo total:* S/. [monto] [o GRATIS si aplica]

*Pasos que debes completar:*
1️⃣ [Paso 1 con dirección y tiempo]
2️⃣ [Paso 2 con dirección y tiempo]
3️⃣ MRE - Jr. Lampa 545 (paso final)

⚠️ *Errores frecuentes que debes evitar:*
• [error 1]
• [error 2]

¿Quieres que te genere un checklist para llevar? Responde *SÍ* y te lo envío.
"""

SYSTEM_PROMPT_VISION = """
Eres RUTAQ, asistente del Ministerio de Relaciones Exteriores del Perú.
Analiza la imagen del documento que te envían y determina:

1. QUÉ TIPO de documento es (título universitario, acta de nacimiento, etc.)
2. QUÉ FIRMAS O SELLOS están presentes (describe lo que ves)
3. QUÉ PODRÍA FALTAR según los requisitos del MRE

Responde en este formato exacto:
📄 *Documento detectado:* [tipo]

✅ *Lo que veo en tu documento:*
• [elemento presente 1]
• [elemento presente 2]

⚠️ *Lo que podría faltar para el MRE:*
• [elemento faltante 1]
• [elemento faltante 2]

📋 *Mi recomendación:*
[Próximo paso concreto que debe tomar]

Sé honesto si no puedes determinar algo con certeza desde la imagen.
"""
async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Transcribe audio con Whisper via Groq"""
    try:
        import io
        # Whisper acepta estos formatos directamente
        # Intentamos con el formato original primero
        for mime in ["audio/ogg", "audio/ogg; codecs=opus", "audio/mpeg", "audio/mp4"]:
            try:
                transcription = groq_client.audio.transcriptions.create(
                    file=("audio.ogg", audio_bytes, mime),
                    model=os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3"),
                    language="es",
                    response_format="text"
                )
                if transcription:
                    return transcription
            except Exception:
                continue
        return None
    except Exception as e:
        print(f"❌ Error transcripción: {e}")
        return None




async def analyze_document_image(image_bytes: bytes) -> str:
    """Analiza imagen de documento con Gemini Vision"""
    model = genai.GenerativeModel("gemini-2.0-flash")
    image_part = {
        "mime_type": "image/jpeg",
        "data": base64.b64encode(image_bytes).decode("utf-8")
    }
    response = model.generate_content([
        SYSTEM_PROMPT_VISION,
        image_part,
        "Analiza este documento y dime qué tipo es y qué podría faltar para apostillarlo en el MRE del Perú."
    ])
    return response.text


async def chat_with_rutaq(user_message: str, conversation_history: list = None) -> str:
    """Responde a mensajes de texto con Groq Llama 3.1"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if conversation_history:
        messages.extend(conversation_history[-6:])  # últimos 3 turnos
    
    messages.append({"role": "user", "content": user_message})
    
    response = groq_client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
        messages=messages,
        max_tokens=1024,
        temperature=0.3,  # bajo para respuestas precisas y consistentes
    )
    return response.choices[0].message.content


async def process_message(
    message_type: str,
    content: str | bytes,
    filename: str = None,
    conversation_history: list = None
) -> str:
    """
    Router principal de RUTAQ.
    Detecta tipo de mensaje y lo procesa con el modelo correcto.
    
    En producción MRE: cambiar Groq por Ollama local (solo cambiar variables de entorno)
    """
    
    if message_type == "text":
        return await chat_with_rutaq(content, conversation_history)
    
    elif message_type == "audio":
     transcribed = await transcribe_audio(content, filename or "audio.ogg")
     if transcribed:
        response = await chat_with_rutaq(
            f"[El usuario envió una nota de voz que dice]: {transcribed}",
            conversation_history
        )
        return f"🎙️ _Escuché:_ \"{transcribed}\"\n\n{response}"
     else:
        # Si no puede transcribir, pedir que escriban
        return (
            "🎙️ No pude entender la nota de voz claramente.\n\n"
            "¿Puedes escribirme qué documento necesitas apostillar? "
            "Por ejemplo: *'Necesito apostillar mi partida de nacimiento'*"
        )
    
    elif message_type == "image":
        # Analizar imagen con Gemini Vision
        vision_analysis = await analyze_document_image(content)
        # Enriquecer con contexto MRE via Llama
        enriched = await chat_with_rutaq(
            f"El usuario envió una foto de su documento. El análisis visual dice: {vision_analysis}. "
            f"Basándote en esto y en los datos del MRE, dale la ruta completa para apostillar.",
            conversation_history
        )
        return enriched
    
    else:
        return (
            "Hola, soy *RUTAQ* 🇵🇪\n\n"
            "Te ayudo a saber exactamente qué pasos seguir para apostillar o legalizar "
            "tu documento en el Ministerio de Relaciones Exteriores.\n\n"
            "Puedes:\n"
            "• ✍️ Escribirme qué documento necesitas apostillar\n"
            "• 📸 Enviarme una foto de tu documento\n"
            "• 🎙️ Mandarme una nota de voz\n\n"
            "¿Qué documento necesitas apostillar hoy?"
        )
