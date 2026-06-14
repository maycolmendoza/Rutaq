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
    import io
    from pydub import AudioSegment
    try:
        # Detectar formato automáticamente (ffmpeg lee el header real)
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        mp3_buffer = io.BytesIO()
        audio.export(mp3_buffer, format="mp3")
        mp3_bytes = mp3_buffer.getvalue()
        print(f"🎙️ Audio convertido a MP3: {len(mp3_bytes)} bytes")

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
        return None


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
     from app.validator import validar_documento_completo, formatear_resultado_whatsapp
     import re
    
    # Analizar imagen con IA
     vision_raw = await analyze_document_image(content)
     if not vision_raw:
        return "No pude analizar la imagen. ¿Puedes enviarla de nuevo con mejor iluminación?"
    
    # Extraer firmantes detectados del análisis
     firmantes = re.findall(
        r'(?:firmado?|firma|sello|certificado?|autorizado?)\s+(?:por\s+)?([A-ZÁÉÍÓÚ][A-ZÁÉÍÓÚ\s]{5,40})',
        vision_raw.upper()
     )
     firmantes = list(set([f.strip() for f in firmantes if len(f.strip()) > 8]))
    
    # Extraer tipo de documento
     tipo_doc = "documento"
     for tipo in ["partida de nacimiento", "título universitario", "acta", 
                 "certificado", "constancia", "poder notarial"]:
        if tipo in vision_raw.lower():
            tipo_doc = tipo
            break
    
    # Validar contra el dataset
     validacion = validar_documento_completo(
        tipo_documento=tipo_doc,
        firmantes_detectados=firmantes,
        fecha_documento=None,
        entidad_emisora=None
     )
    
    # Generar dos mensajes
     msg1, msg2 = formatear_resultado_whatsapp(validacion, tipo_doc)
    
    # Enriquecer con pasos del MRE
     pasos = await chat_with_rutaq(
        f"El usuario tiene un {tipo_doc} para apostillar. "
        f"Validación: {validacion['porcentaje']}% aceptación. "
        f"Problemas: {validacion['rechazos']}. "
        f"Dale los pasos específicos para corregir y apostillar, en lenguaje simple.",
        conversation_history
     )
    
     return f"{msg1}\n\n{msg2}\n\n📋 *Qué hacer ahora:*\n{pasos}"
    
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
