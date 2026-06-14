import os
import json
import base64
from groq import Groq
from pathlib import Path

# ── Clientes ──────────────────────────────────────────────
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Datos MRE ─────────────────────────────────────────────
DATA_PATH = Path(__file__).parent.parent / "data" / "cadena_mre.json"
AUTH_PATH = Path(__file__).parent.parent / "data" / "autoridades_mre.json"

with open(DATA_PATH, "r", encoding="utf-8") as f:
    MRE_DATA = json.load(f)

with open(AUTH_PATH, "r", encoding="utf-8") as f:
    AUTORIDADES_DATA = json.load(f)

SYSTEM_PROMPT = f"""
Eres RUTAQ, asistente digital oficial del Ministerio de Relaciones Exteriores del Perú.
Tu nombre significa "el que encuentra el camino" en quechua.
Hablas español, quechua y aymara con fluidez natural.

MISIÓN: Ayudar al ciudadano a conocer los pasos EXACTOS para apostillar o legalizar 
documentos ANTES de ir al MRE, evitando el rechazo en ventanilla (tasa actual: 30%).

CADENA DE CERTIFICACIONES OFICIAL DEL MRE:
{json.dumps(MRE_DATA, ensure_ascii=False, indent=2)}

AUTORIDADES FIRMANTES REGISTRADAS EN CANCILLERÍA:
{json.dumps(AUTORIDADES_DATA['por_entidad'], ensure_ascii=False, indent=2)}

REGLAS CRÍTICAS:
1. Detecta el idioma del usuario (español/quechua/aymara) y responde en ese idioma
2. USA SOLO datos oficiales — nunca inventes información
3. Lenguaje simple — nunca digas "cadena de certificación"
4. Siempre incluye pasos numerados, tiempos, costos, direcciones
5. Menciona GRATUIDAD para peruanos cuando aplique
6. Da siempre un PORCENTAJE DE PROBABILIDAD DE ACEPTACIÓN
7. Si menciona distrito/ciudad, indica la oficina más cercana
8. Ignora mensajes cortos como "ok", "bien", "gracias" — no respondas nada

FORMATO DE RESPUESTA:
📄 *Documento:* [tipo]
⏱️ *Tiempo total:* [X días hábiles]
💰 *Costo total:* S/. [monto]

*Pasos antes de ir al MRE:*
1️⃣ [Paso con entidad, dirección, tiempo]
2️⃣ [Siguiente paso]
3️⃣ MRE — Jr. Lampa 545 ✅

⚠️ *Errores frecuentes:*
- [error específico]

✅ *Probabilidad de aceptación: XX%*

¿Quieres un checklist personalizado? Responde *SÍ*
"""

SYSTEM_PROMPT_VISION = f"""
Eres RUTAQ, asistente oficial del MRE del Perú. Analiza documentos para apostilla.

AUTORIDADES FIRMANTES VIGENTES REGISTRADAS EN CANCILLERÍA:
{json.dumps(AUTORIDADES_DATA['por_entidad'], ensure_ascii=False, indent=2)}

Al analizar la imagen:
1. IDENTIFICA el tipo de documento
2. DETECTA firmas, sellos, códigos QR presentes
3. VERIFICA si las firmas corresponden a autoridades registradas
4. CALCULA porcentaje de probabilidad de aceptación
5. INDICA exactamente qué falta

FORMATO OBLIGATORIO:
📄 *Documento detectado:* [tipo exacto]

🔍 *Análisis de firmas y sellos:*
✅ [lo que SÍ tiene]
❌ [lo que le FALTA]

📊 *Probabilidad de aceptación en MRE:* [X]%
[Explicación breve]

📋 *Pasos antes del MRE:*
1️⃣ [paso con dirección]
2️⃣ [siguiente]

⚠️ *Riesgo principal de rechazo:* [el más crítico]
"""


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    import io
    from pydub import AudioSegment
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        mp3_buffer = io.BytesIO()
        audio.export(mp3_buffer, format="mp3")
        mp3_bytes = mp3_buffer.getvalue()
        print(f"🎙️ Audio convertido: {len(mp3_bytes)} bytes")
        transcription = groq_client.audio.transcriptions.create(
            file=("audio.mp3", mp3_bytes, "audio/mpeg"),
            model=os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3"),
            language="es",
            response_format="text"
        )
        print(f"🎙️ Transcrito: {transcription}")
        return transcription
    except Exception as e:
        print(f"❌ Error transcripción: {e}")
        return None


async def analyze_document_image(image_bytes: bytes) -> str:
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    try:
        response = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT_VISION
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                        }
                    ]
                }
            ],
            max_tokens=1500,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Error visión: {e}")
        return f"No pude analizar la imagen: {e}"


async def chat_with_rutaq(user_message: str, conversation_history: list = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history[-6:])
    messages.append({"role": "user", "content": user_message})
    response = groq_client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=messages,
        max_tokens=1200,
        temperature=0.2,
    )
    return response.choices[0].message.content


async def process_message(
    message_type: str,
    content,
    filename: str = None,
    conversation_history: list = None
) -> str:
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
            return (
                "🎙️ No pude escuchar bien tu nota de voz.\n\n"
                "¿Puedes escribirme qué documento necesitas apostillar?\n"
                "Ejemplo: *'Necesito apostillar mi partida de nacimiento'*"
            )

    elif message_type == "image":
        vision_analysis = await analyze_document_image(content)
        enriched = await chat_with_rutaq(
            f"El usuario envió una foto de su documento. "
            f"Análisis visual: {vision_analysis}. "
            f"Brinda orientación completa con porcentaje de aceptación.",
            conversation_history
        )
        return enriched

    else:
        return (
            "¡Hola! Soy *RUTAQ* 🇵🇪\n"
            "_\"El que encuentra el camino\"_\n\n"
            "Soy el asistente digital del MRE. Te ayudo a apostillar "
            "sin ser rechazado en ventanilla.\n\n"
            "*Puedes:*\n"
            "✍️ Escribirme en español, quechua o aymara\n"
            "📸 Enviarme una foto de tu documento\n"
            "🎙️ Mandarme una nota de voz\n"
            "📄 Subir el PDF de tu documento\n\n"
            "¿Qué documento necesitas apostillar hoy?"
        )
