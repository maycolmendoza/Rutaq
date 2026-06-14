import json
import re
from pathlib import Path
from datetime import datetime

# Cargar datos
AUTH_PATH = Path(__file__).parent.parent / "data" / "autoridades_mre.json"
with open(AUTH_PATH, "r", encoding="utf-8") as f:
    AUTORIDADES_DATA = json.load(f)

def extraer_fecha_documento(texto_ocr: str) -> str | None:
    """Extrae fecha del documento desde el texto del análisis de visión"""
    patrones = [
        r'(\d{2})[/\-\.](\d{2})[/\-\.](\d{4})',  # DD/MM/YYYY
        r'(\d{4})[/\-\.](\d{2})[/\-\.](\d{2})',  # YYYY/MM/DD
        r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})',  # DD de Mes de YYYY
    ]
    meses = {
        'enero':'01','febrero':'02','marzo':'03','abril':'04',
        'mayo':'05','junio':'06','julio':'07','agosto':'08',
        'septiembre':'09','octubre':'10','noviembre':'11','diciembre':'12'
    }
    for patron in patrones:
        match = re.search(patron, texto_ocr.lower())
        if match:
            grupos = match.groups()
            if len(grupos) == 3:
                if grupos[2].isdigit() and len(grupos[2]) == 4:
                    mes = meses.get(grupos[1], grupos[1])
                    return f"{grupos[2]}{mes.zfill(2)}{grupos[0].zfill(2)}"
                elif len(grupos[0]) == 4:
                    return f"{grupos[0]}{grupos[1]}{grupos[2]}"
                else:
                    return f"{grupos[2]}{grupos[1]}{grupos[0]}"
    return None


def buscar_firmante_en_dataset(nombre_detectado: str, entidad: str = None) -> dict:
    """
    Busca si un nombre detectado en el documento existe en el dataset.
    Retorna: {encontrado, vigente, periodo, entidad, cargo, alerta}
    """
    nombre_upper = nombre_detectado.upper().strip()
    palabras = [p for p in nombre_upper.split() if len(p) > 3]
    
    mejor_match = None
    mejor_score = 0
    
    entidades_buscar = AUTORIDADES_DATA["por_entidad"]
    if entidad:
        entidades_filtradas = {k: v for k, v in entidades_buscar.items() 
                               if entidad.upper() in k}
        if entidades_filtradas:
            entidades_buscar = entidades_filtradas

    for nombre_entidad, data in entidades_buscar.items():
        for categoria in ["vigentes", "historicos"]:
            for autoridad in data[categoria]:
                nombre_auth = autoridad["nombre"].upper()
                score = sum(1 for p in palabras if p in nombre_auth)
                if score > mejor_score and score >= 2:
                    mejor_score = score
                    mejor_match = {
                        "encontrado": True,
                        "nombre": autoridad["nombre"],
                        "cargo": autoridad["cargo"],
                        "entidad": nombre_entidad,
                        "vigente": categoria == "vigentes",
                        "periodo": autoridad.get("vigente_hasta") or autoridad.get("periodo", ""),
                    }

    if not mejor_match:
        return {
            "encontrado": False,
            "alerta": f"⚠️ '{nombre_detectado}' NO está registrado en Cancillería"
        }
    
    if mejor_match["vigente"]:
        mejor_match["alerta"] = f"✅ Firma válida y vigente hasta {mejor_match['periodo'][:4]}"
    else:
        mejor_match["alerta"] = f"❌ Firma EXPIRADA — mandato terminó en periodo {mejor_match['periodo']}"
    
    return mejor_match


def validar_documento_completo(
    tipo_documento: str,
    firmantes_detectados: list[str],
    fecha_documento: str = None,
    entidad_emisora: str = None
) -> dict:
    """
    Validación completa del documento.
    Retorna análisis detallado con porcentaje de aceptación.
    """
    alertas = []
    aprobados = []
    rechazos = []
    
    # Validar cada firmante detectado
    for firmante in firmantes_detectados:
        resultado = buscar_firmante_en_dataset(firmante, entidad_emisora)
        
        if not resultado["encontrado"]:
            rechazos.append(resultado["alerta"])
        elif not resultado["vigente"]:
            # Validar si la fecha del documento cae dentro del mandato
            if fecha_documento and resultado.get("periodo"):
                periodo = resultado["periodo"]
                if "-" in periodo:
                    inicio, fin = periodo.split("-")
                    if inicio <= fecha_documento <= fin:
                        aprobados.append(
                            f"✅ {resultado['nombre']} ({resultado['cargo']}) — "
                            f"firma válida para la fecha del documento"
                        )
                    else:
                        rechazos.append(
                            f"❌ {resultado['nombre']} — firmó el {fecha_documento[:4]} "
                            f"pero su mandato fue {periodo} — CADENA ROTA"
                        )
                else:
                    rechazos.append(resultado["alerta"])
            else:
                alertas.append(
                    f"⚠️ {resultado['nombre']} ({resultado['cargo']}) — "
                    f"mandato vencido, verificar fecha del documento"
                )
        else:
            aprobados.append(resultado["alerta"] + f" — {resultado['nombre']} ({resultado['cargo']})")

    # Calcular porcentaje
    total = len(firmantes_detectados) if firmantes_detectados else 1
    puntaje = (len(aprobados) / total) * 100 if total > 0 else 50
    
    # Ajustar por alertas
    puntaje -= len(rechazos) * 25
    puntaje -= len(alertas) * 10
    puntaje = max(0, min(100, puntaje))

    return {
        "aprobados": aprobados,
        "alertas": alertas,
        "rechazos": rechazos,
        "porcentaje": round(puntaje),
        "recomendacion": _generar_recomendacion(puntaje, rechazos, alertas)
    }


def _generar_recomendacion(puntaje: float, rechazos: list, alertas: list) -> str:
    if puntaje >= 90:
        return "🟢 Tu documento tiene alta probabilidad de ser aceptado. Procede al MRE."
    elif puntaje >= 70:
        return "🟡 Documento con observaciones menores. Revisa las alertas antes de ir al MRE."
    elif puntaje >= 40:
        return "🟠 Documento con problemas importantes. Corrige los rechazos antes de ir al MRE."
    else:
        return "🔴 Alta probabilidad de rechazo. No vayas al MRE aún — corrige los errores primero."


def formatear_resultado_whatsapp(validacion: dict, tipo_doc: str) -> tuple[str, str]:
    """
    Genera DOS mensajes para WhatsApp:
    1. Análisis detallado con firmas
    2. Veredicto final con porcentaje
    """
    # Mensaje 1 — Análisis detallado
    msg1 = f"🔍 *Análisis de tu {tipo_doc}*\n\n"
    
    if validacion["aprobados"]:
        msg1 += "*Lo que está correcto:*\n"
        for a in validacion["aprobados"]:
            msg1 += f"{a}\n"
        msg1 += "\n"
    
    if validacion["alertas"]:
        msg1 += "*⚠️ Observaciones:*\n"
        for a in validacion["alertas"]:
            msg1 += f"{a}\n"
        msg1 += "\n"
    
    if validacion["rechazos"]:
        msg1 += "*❌ Problemas críticos:*\n"
        for r in validacion["rechazos"]:
            msg1 += f"{r}\n"

    # Mensaje 2 — Veredicto
    porcentaje = validacion["porcentaje"]
    if porcentaje >= 90:
        emoji = "🟢"
    elif porcentaje >= 70:
        emoji = "🟡"
    elif porcentaje >= 40:
        emoji = "🟠"
    else:
        emoji = "🔴"

    msg2 = (
        f"{emoji} *Probabilidad de aceptación en el MRE*\n\n"
        f"*{porcentaje}%*\n\n"
        f"{validacion['recomendacion']}\n\n"
        f"¿Quieres saber a qué oficina ir más cercana a ti? "
        f"Comparte tu ubicación 📍 o dime tu distrito."
    )
    
    return msg1, msg2
