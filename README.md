# RUTAQ 🇵🇪
### *"El que encuentra el camino"* — Quechua

Asistente IA para orientación de apostilla y legalización del MRE Perú.
**Hackatón TransformaGob 2026 — Desafío MRE #9**

---

## El problema
1 de cada 3 ciudadanos (30%) que acude al MRE es rechazado en ventanilla porque no conoce la cadena de certificaciones previa. Son 18,600 personas al mes que pierden días, dinero y permisos de trabajo.

## La solución
RUTAQ es un agente IA en WhatsApp que orienta al ciudadano ANTES de salir de casa:
- 💬 Texto en español o quechua
- 📸 Foto del documento → detecta qué firmas faltan
- 🎙️ Nota de voz → transcribe y responde

---

## Stack tecnológico

| Componente | Demo | Producción MRE |
|---|---|---|
| Canal | Meta WhatsApp Cloud API | Meta WhatsApp Business |
| Backend | FastAPI + Railway | FastAPI + Servidor MRE |
| LLM texto | Groq + Llama 3.1 70B | Ollama + Llama 3.1 70B local |
| LLM visión | Gemini Flash 1.5 | LLaVA local |
| Audio | Whisper v3 (Groq) | Whisper.cpp local |
| Datos | JSON local + CSV MRE | PostgreSQL servidor MRE |

**Costo demo: ~$0 USD | Costo producción: $0-150/mes**

---

## Instalación local

```bash
git clone https://github.com/tu-usuario/rutaq
cd rutaq
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tus credenciales
uvicorn main:app --reload
```

## Variables de entorno necesarias

```env
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_VERIFY_TOKEN=rutaq2026
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

## Deploy en Railway

1. Crear cuenta en railway.app
2. New Project → Deploy from GitHub
3. Agregar variables de entorno
4. El webhook URL será: `https://tu-app.railway.app/webhook`

## Migración a producción MRE

Solo cambiar 3 variables de entorno — el código no cambia:

```env
# De Groq:
GROQ_API_KEY=gsk_...

# A Ollama local:
GROQ_BASE_URL=http://localhost:11434/v1
GROQ_API_KEY=ollama
GROQ_MODEL=llama3.1:70b
```

---

## Licencia
MIT License — Software libre para uso, modificación y distribución por entidades públicas.
Compatible con DL 1412 Art. 29 — Ley de Gobierno Digital del Perú.
