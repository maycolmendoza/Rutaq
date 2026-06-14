import json
import re
from pathlib import Path
from datetime import datetime

# Cargar datos de autoridades
AUTH_PATH = Path(__file__).parent.parent / "data" / "autoridades_mre.json"
with open(AUTH_PATH, "r", encoding="utf-8") as f:
    AUTORIDADES_DATA = json.load(f)


def normalizar_nombre(nombre: str) -> str:
    """Normaliza nombre para comparación: mayúsculas, sin tildes, sin espacios extra"""
    replacements = {
        'Á':'A','É':'E','Í':'I','Ó':'O','Ú':'U',
        'á':'a','é':'e','í':'i','ó':'o','ú':'u','ñ':'n','Ñ':'N'
    }
    nombre = nombre.upper().strip()
    for k, v in replacements.items():
        nombre = nombre.replace(k, v)
    return ' '.join(nombre.split())


def fecha_a_yyyymmdd(texto_fecha: str) -> str | None:
    """Convierte varios formatos de fecha a YYYYMMDD"""
    meses = {
        'enero':'01','febrero':'02','marzo':'03','abril':'04',
        'mayo':'05','junio':'06','julio':'07','agosto':'08',
        'septiembre':'09','octubre':'10','noviembre':'11','diciembre':'12',
        'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
        'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'
    }
    texto = texto_fecha.lower().strip()

    # DD/MM/YYYY o DD-MM-YYYY
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})', texto)
    if m:
        return f"{m.group(3)}{m.group(2).zfill(2)}{m.group(1).zfill(2)}"

    # YYYY/MM/DD
    m = re.search(r'(\d{4})[/\-\.](\d{2})[/\-\.](\d{2})', texto)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"

    # DD de mes de YYYY
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})', texto)
    if m:
        mes = meses.get(m.group(2).lower())
        if mes:
            return f"{m.group(3)}{mes}{m.group(1).zfill(2)}"

    # Solo año YYYY
    m = re.search(r'\b(20\d{2})\b', texto)
    if m:
        return f"{m.group(1)}0101"

    return None


def buscar_firmante(nombre_detectado: str, fecha_documento: str = None) -> dict:
    """
    Busca un nombre en el dataset y valida si su firma es válida
    para la fecha del documento.
    
    Retorna dict con: encontrado, valido, nombre, cargo, entidad, 
                      periodo, alerta, nivel (ok/warning/error)
    """
    nombre_norm = normalizar_nombre(nombre_detectado)
    palabras = [p for p in nombre_norm.split() if len(p) > 3]

    if len(palabras) < 2:
        return {
            "encontrado": False,
            "valido": False,
            "nivel": "error",
            "alerta": f"❌ '{nombre_detectado}' — nombre muy corto para verificar"
        }

    mejor_match = None
    mejor_score = 0

    for entidad, data in AUTORIDADES_DATA["por_entidad"].items():
        for categoria in ["vigentes", "historicos"]:
            for autoridad in data[categoria]:
                nombre_auth = normalizar_nombre(autoridad["nombre"])
                # Coincidencia por palabras clave
                score = sum(1 for p in palabras if p in nombre_auth)
                # Bonus si coinciden 3+ palabras
                if score > mejor_score and score >= 2:
                    mejor_score = score
                    mejor_match = {
                        "nombre": autoridad["nombre"],
                        "cargo": autoridad["cargo"],
                        "entidad": entidad,
                        "categoria": categoria,
                        "periodo": autoridad.get("vigente_hasta") or autoridad.get("periodo", ""),
                    }

    if not mejor_match:
        return {
            "encontrado": False,
            "valido": False,
            "nivel": "error",
            "alerta": (
                f"❌ *{nombre_detectado}* no está registrado en Cancillería.\n"
                f"   → Esta firma no será reconocida por el MRE."
            )
        }

    nombre = mejor_match["nombre"]
    cargo = mejor_match["cargo"]
    entidad = mejor_match["entidad"]
    periodo = mejor_match["periodo"]
    categoria = mejor_match["categoria"]

    # Autoridad vigente HOY
    if categoria == "vigentes":
        vigente_hasta = periodo[:4]
        return {
            "encontrado": True,
            "valido": True,
            "nivel": "ok",
            "nombre": nombre,
            "cargo": cargo,
            "entidad": entidad,
            "alerta": (
                f"✅ *{nombre}* — {cargo}\n"
                f"   Entidad: {entidad}\n"
                f"   Vigente hasta: {vigente_hasta} ✓"
            )
        }

    # Autoridad histórica — validar contra fecha del documento
    if "-" in periodo:
        inicio, fin = periodo.split("-")
    else:
        inicio = fin = periodo

    if fecha_documento:
        fecha_norm = fecha_a_yyyymmdd(fecha_documento) or fecha_documento

        if inicio <= fecha_norm <= fin:
            # Firma válida para esa fecha
            return {
                "encontrado": True,
                "valido": True,
                "nivel": "ok",
                "nombre": nombre,
                "cargo": cargo,
                "entidad": entidad,
                "alerta": (
                    f"✅ *{nombre}* — {cargo}\n"
                    f"   Entidad: {entidad}\n"
                    f"   Firmó el {fecha_documento} dentro de su mandato "
                    f"({inicio[:4]}–{fin[:4]}) ✓"
                )
            }
        else:
            # CADENA ROTA — firmó fuera de su mandato
            return {
                "encontrado": True,
                "valido": False,
                "nivel": "error",
                "nombre": nombre,
                "cargo": cargo,
                "entidad": entidad,
                "alerta": (
                    f"❌ *{nombre}* — {cargo}\n"
                    f"   Entidad: {entidad}\n"
                    f"   ⚠️ CADENA ROTA: firmó el {fecha_documento} pero su mandato "
                    f"fue {inicio[:4]}–{fin[:4]}.\n"
                    f"   → El MRE rechazará este documento."
                )
            }
    else:
        # No tenemos fecha del documento — alertar
        return {
            "encontrado": True,
            "valido": None,
            "nivel": "warning",
            "nombre": nombre,
            "cargo": cargo,
            "entidad": entidad,
            "alerta": (
                f"⚠️ *{nombre}* — {cargo}\n"
                f"   Entidad: {entidad}\n"
                f"   Su mandato fue {inicio[:4]}–{fin[:4]}.\n"
                f"   No pude verificar si la fecha del documento cae en ese periodo.\n"
                f"   → Verifica la fecha de emisión de tu documento."
            )
        }


def validar_documento(
    firmantes_detectados: list[str],
    fecha_documento: str = None,
    tipo_documento: str = "documento"
) -> dict:
    """
    Valida todos los firmantes detectados y calcula porcentaje de aceptación.
    """
    if not firmantes_detectados:
        return {
            "resultados": [],
            "porcentaje": 50,
            "nivel_general": "warning",
            "resumen": "⚠️ No se detectaron firmantes claros en el documento.",
            "veredicto": "No puedo validar sin detectar las firmas. Intenta con mejor resolución."
        }

    resultados = []
    for firmante in firmantes_detectados:
        r = buscar_firmante(firmante, fecha_documento)
        resultados.append(r)

    # Calcular puntaje
    total = len(resultados)
    ok = sum(1 for r in resultados if r.get("nivel") == "ok")
    warnings = sum(1 for r in resultados if r.get("nivel") == "warning")
    errors = sum(1 for r in resultados if r.get("nivel") == "error")

    porcentaje = max(0, min(100, int((ok / total) * 100 - (errors * 20))))

    if porcentaje >= 85:
        nivel = "ok"
        veredicto = (
            f"🟢 *Probabilidad de aceptación: {porcentaje}%*\n"
            f"Tu documento tiene buenas chances de ser aceptado en ventanilla.\n"
            f"Procede a completar los pasos faltantes y ve al MRE."
        )
    elif porcentaje >= 60:
        nivel = "warning"
        veredicto = (
            f"🟡 *Probabilidad de aceptación: {porcentaje}%*\n"
            f"Tu documento tiene observaciones. Corrígelas antes de ir al MRE\n"
            f"para evitar ser rechazado en ventanilla."
        )
    elif porcentaje >= 30:
        nivel = "warning"
        veredicto = (
            f"🟠 *Probabilidad de aceptación: {porcentaje}%*\n"
            f"Tu documento tiene problemas importantes.\n"
            f"No vayas al MRE todavía — corrige los errores primero."
        )
    else:
        nivel = "error"
        veredicto = (
            f"🔴 *Probabilidad de aceptación: {porcentaje}%*\n"
            f"Alta probabilidad de rechazo en ventanilla.\n"
            f"Debes corregir todos los problemas antes de ir al MRE."
        )

    return {
        "resultados": resultados,
        "porcentaje": porcentaje,
        "nivel_general": nivel,
        "fecha_detectada": fecha_documento,
        "veredicto": veredicto
    }


def formatear_dos_mensajes(validacion: dict, tipo_doc: str) -> tuple[str, str]:
    """
    Genera 2 mensajes para WhatsApp:
    Mensaje 1: Análisis detallado firma por firma
    Mensaje 2: Veredicto final con porcentaje
    """
    resultados = validacion["resultados"]

    # ── Mensaje 1: Análisis detallado ──
    msg1 = f"🔍 *Análisis de firmas — {tipo_doc.title()}*\n"
    if validacion.get("fecha_detectada"):
        msg1 += f"📅 Fecha del documento: {validacion['fecha_detectada']}\n"
    msg1 += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    ok_list = [r for r in resultados if r.get("nivel") == "ok"]
    warn_list = [r for r in resultados if r.get("nivel") == "warning"]
    err_list = [r for r in resultados if r.get("nivel") == "error"]

    if ok_list:
        msg1 += "✅ *Firmas válidas:*\n"
        for r in ok_list:
            msg1 += f"{r['alerta']}\n\n"

    if warn_list:
        msg1 += "⚠️ *Observaciones:*\n"
        for r in warn_list:
            msg1 += f"{r['alerta']}\n\n"

    if err_list:
        msg1 += "❌ *Problemas críticos:*\n"
        for r in err_list:
            msg1 += f"{r['alerta']}\n\n"

    if not resultados:
        msg1 += "No se pudieron verificar firmantes en el documento.\n"

    # ── Mensaje 2: Veredicto final ──
    msg2 = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{validacion['veredicto']}\n\n"
        f"📍 ¿Quieres saber a qué oficina ir más cercana?\n"
        f"Comparte tu ubicación 📍 o escribe tu distrito."
    )

    return msg1, msg2
