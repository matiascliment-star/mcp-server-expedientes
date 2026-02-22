import os
import json
import math
import re
from datetime import datetime, timedelta, timezone
import httpx
from fastmcp import FastMCP

# --- Config ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
PORT = int(os.environ.get("PORT", 8000))

# --- MCP Server ---
mcp = FastMCP("Expedientes Legales", stateless_http=True, json_response=True)


# ============================================================
# TRADUCCIÓN DE MOVIMIENTOS (misma lógica que portal-clientes)
# ============================================================

def traducir_movimiento(tipo: str, descripcion: str, es_srt: bool = False) -> str:
    desc = (descripcion or "").lower()
    tip = (tipo or "").lower()

    es_escrito = "escrito" in tip
    es_despacho = "despacho" in tip
    es_mov = "movimiento" in tip
    es_cedula = "cedula" in tip or "cédula" in tip or desc.startswith("cédula")
    es_evento = "evento" in tip

    if es_cedula:
        return "Notificación" if es_srt else "Notificación judicial"
    if "honorario" in desc:
        return "Regulación de costas" if "regul" in desc else "Resolución del juzgado"
    if es_despacho:
        if "sentencia" in desc and "dicte" not in desc:
            return "Trámite de sentencia"
        if "alegar" in desc or "alegato" in desc:
            return "Juzgado habilitó alegatos"
        if "apertura" in desc or "abre a prueba" in desc:
            return "Juzgado abrió a prueba"
        if "traslado" in desc:
            return "Juzgado ordenó traslado"
        if "perit" in desc or "sorteo" in desc:
            return "Resolución sobre pericia"
        if "intim" in desc:
            return "Intimación del juzgado"
        if "sin perjuicio" in desc or "agreg" in desc:
            return "Proveído del juzgado"
        return "Resolución del juzgado"
    if es_escrito:
        if "apela" in desc or "recurso" in desc:
            return "Recurso presentado"
        if "alegato" in desc:
            return "Trámite de alegato"
        if "pericia" in desc or "informe pericial" in desc:
            return "Trámite de pericia"
        if "contesta" in desc and "demanda" in desc:
            return "Contestación de demanda"
        if "demanda" in desc and "contesta" not in desc:
            return "Demanda presentada"
        if "ofrec" in desc and "prueba" in desc:
            return "Ofrecimiento de prueba"
        if "solicita" in desc or "pide" in desc or "insiste" in desc:
            return "Escrito presentado"
        return "Escrito presentado"
    if es_mov:
        if "en letra" in desc:
            return "Expediente en letra"
        if "en despacho" in desc:
            return "Expediente en despacho"
        if "alegar" in desc:
            return "Pase a alegar"
        if "archivo" in desc or "paralizad" in desc:
            return "Expediente archivado"
        return "Movimiento del expediente"
    if es_evento:
        return "Notificación" if "notificacion" in desc else "Evento procesal"

    # Fallbacks SRT
    if "citacion" in desc or "citación" in desc:
        return "Se programó una citación"
    if "audiencia virtual" in desc:
        return "Audiencia virtual realizada"
    if "audiencia" in desc:
        return "Se realizó una audiencia"
    if "dictamen" in desc and "medico" in desc:
        return "Se emitió dictamen médico"
    if "homolog" in desc:
        return "Se homologó el acuerdo"
    if "acuerdo" in desc or "concilia" in desc:
        return "Negociación de acuerdo"
    if "historia clinica" in desc or "hc solicit" in desc:
        return "Se solicitó historia clínica"
    if "itm" in desc or "incapacidad" in desc:
        return "Determinación de incapacidad"

    # Otros fallbacks
    if "notifica" in desc or "cédula" in desc or "cedula" in desc:
        return "Notificación" if es_srt else "Notificación judicial"
    if "sentencia" in desc or "fallo" in desc:
        return "Trámite de sentencia"
    if "pericia" in desc or "perito" in desc:
        return "Trámite de pericia"
    if "alegato" in desc or "alegar" in desc:
        return "Trámite de alegatos"
    if "apela" in desc or "recurso" in desc:
        return "Recurso presentado"
    if "elev" in desc or "remit" in desc:
        return "Expediente elevado"
    if "deposito" in desc or "pago" in desc or "embargo" in desc:
        return "Movimiento de cobro"
    if "poder" in desc or "apoderado" in desc:
        return "Gestión de representación"

    texto = (descripcion or tipo or "Trámite").replace("honorarios", "costas").replace("Honorarios", "Costas")
    return texto[:50] if len(texto) > 50 else texto


# ============================================================
# ESTADO → ETAPA (misma lógica que portal-clientes)
# ============================================================

ESTADO_A_ETAPA = {
    "01": 1, "02": 1, "03": 1, "04": 1, "05": 1, "06": 1,
    "10": 2, "11": 2, "12": 2, "13": 2, "14": 2, "15": 2,
    "16": 2, "17": 2, "18": 2, "19": 2, "20": 2, "21": 2, "22": 2, "23": 2,
    "30": 3, "31": 3, "32": 3, "33": 3, "34": 3, "35": 3, "36": 3,
    "40": 4, "41": 4, "42": 4, "43": 4, "44": 4,
    "50": 5, "51": 5, "52": 5, "53": 5, "54": 5, "55": 5, "56": 5, "57": 5,
    "60": 6, "61": 6, "62": 6, "63": 6, "64": 6,
    "70": 7, "71": 7, "72": 7, "73": 7, "74": 7, "75": 7, "76": 7, "77": 7,
    "80": 8, "81": 8, "82": 8, "83": 8, "84": 8,
    "90": 1, "91": 1, "92": 1,
}


def extraer_etapa(estado_str: str) -> int:
    if not estado_str:
        return 1
    match = re.match(r"(\d+)", estado_str)
    if not match:
        return 1
    num = match.group(1).zfill(2)
    return ESTADO_A_ETAPA.get(num, 1)


# ============================================================
# SEGUIMIENTOS POR ETAPA (misma data que portal-clientes)
# ============================================================

SEGUIMIENTOS_JUDICIAL = {
    1: {
        "unaVez": [
            {"tipo": "armado_carpeta", "texto": "Armado de carpeta del expediente judicial"},
            {"tipo": "analisis_contestacion", "texto": "Análisis de contestación de demanda"},
            {"tipo": "revision_documental", "texto": "Revisión de documentación del caso"},
        ],
        "muchasVeces": [
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
        ],
    },
    2: {
        "unaVez": [
            {"tipo": "preparacion_pericia", "texto": "Preparación de pericias"},
            {"tipo": "analisis_pericia", "texto": "Análisis de pericia presentada", "requierePericia": True},
            {"tipo": "coordinacion_informativa", "texto": "Coordinación de prueba informativa"},
            {"tipo": "coordinacion_turnos", "texto": "Coordinación y revisión de turnos médicos"},
        ],
        "muchasVeces": [
            {"tipo": "gestion_estudios", "texto": "Gestión por estudios complementarios"},
            {"tipo": "revision_estudios", "texto": "Revisión de resultados médicos"},
            {"tipo": "reunion_equipo_medico", "texto": "Caso tratado en reunión con equipo médico"},
            {"tipo": "seguimiento_perito", "texto": "Seguimiento al perito designado"},
            {"tipo": "control_vencimientos", "texto": "Control de vencimientos"},
            {"tipo": "reunion_estrategia", "texto": "Caso tratado en reunión de estrategia procesal"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    3: {
        "unaVez": [
            {"tipo": "preparacion_pruebas_alegato", "texto": "Preparación de pruebas para alegato"},
            {"tipo": "redaccion_alegato", "texto": "Redacción de alegato"},
            {"tipo": "control_alegato", "texto": "Control de alegato"},
            {"tipo": "revision_pruebas", "texto": "Revisión integral de pruebas"},
            {"tipo": "analisis_jurisprudencia", "texto": "Análisis de jurisprudencia"},
        ],
        "muchasVeces": [
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    4: {
        "unaVez": [
            {"tipo": "analisis_antecedentes", "texto": "Análisis de antecedentes del juzgado"},
        ],
        "muchasVeces": [
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    5: {
        "unaVez": [
            {"tipo": "control_sorteo_sala", "texto": "Control de sorteo de sala"},
            {"tipo": "revision_apelacion", "texto": "Revisión de la apelación"},
            {"tipo": "analisis_sala", "texto": "Análisis de criterio de la sala"},
        ],
        "muchasVeces": [
            {"tipo": "seguimiento_camara", "texto": "Seguimiento en Cámara"},
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    6: {
        "unaVez": [
            {"tipo": "analisis_admisibilidad", "texto": "Análisis de admisibilidad"},
        ],
        "muchasVeces": [
            {"tipo": "seguimiento_corte", "texto": "Seguimiento en Corte"},
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    7: {
        "unaVez": [
            {"tipo": "analisis_sentencia", "texto": "Análisis de parámetros de la sentencia"},
        ],
        "muchasVeces": [
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    8: None,  # Finalizados - no generar
}

SEGUIMIENTOS_DESPIDO = {
    1: {
        "unaVez": [
            {"tipo": "armado_carpeta", "texto": "Armado de carpeta del expediente judicial"},
            {"tipo": "analisis_contestacion", "texto": "Análisis de contestación de demanda"},
            {"tipo": "revision_documental", "texto": "Revisión de documentación del caso"},
        ],
        "muchasVeces": [
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
        ],
    },
    2: {
        "unaVez": [
            {"tipo": "coordinacion_testigos", "texto": "Coordinación de testigos"},
            {"tipo": "coordinacion_informativa", "texto": "Coordinación de prueba informativa"},
        ],
        "muchasVeces": [
            {"tipo": "seguimiento_informes", "texto": "Seguimiento de informes"},
            {"tipo": "reunion_estrategia", "texto": "Caso tratado en reunión de estrategia procesal"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    3: {
        "unaVez": [
            {"tipo": "preparacion_pruebas_alegato", "texto": "Preparación de pruebas para alegato"},
            {"tipo": "redaccion_alegato", "texto": "Redacción de alegato"},
            {"tipo": "control_alegato", "texto": "Control de alegato"},
            {"tipo": "revision_pruebas", "texto": "Revisión integral de pruebas"},
        ],
        "muchasVeces": [
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    4: {
        "unaVez": [
            {"tipo": "analisis_antecedentes", "texto": "Análisis de antecedentes del juzgado"},
        ],
        "muchasVeces": [
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    5: {
        "unaVez": [
            {"tipo": "control_sorteo_sala", "texto": "Control de sorteo de sala"},
            {"tipo": "revision_apelacion", "texto": "Revisión de la apelación"},
            {"tipo": "analisis_sala", "texto": "Análisis de criterio de la sala"},
        ],
        "muchasVeces": [
            {"tipo": "seguimiento_camara", "texto": "Seguimiento en Cámara"},
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    6: {
        "unaVez": [
            {"tipo": "analisis_sentencia", "texto": "Análisis de parámetros de la sentencia"},
        ],
        "muchasVeces": [
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "actualizacion_sistema", "texto": "Actualización en sistema interno"},
            {"tipo": "consulta_mesa", "texto": "Consulta en mesa de entradas"},
            {"tipo": "consulta_tribunales", "texto": "Consulta en Tribunales"},
            {"tipo": "seguimiento_notificaciones", "texto": "Seguimiento de notificaciones"},
            {"tipo": "control_plazos", "texto": "Control de plazos procesales"},
            {"tipo": "reunion_equipo", "texto": "Caso tratado en reunión de equipo"},
        ],
    },
    7: None,  # Cobrado
}

SEGUIMIENTOS_SRT = {
    0: None,  # En tratamiento - no generar
    1: {
        "unaVez": [
            {"tipo": "carga_sistema", "texto": "Carga en sistema interno"},
            {"tipo": "revision_caso", "texto": "Revisión del caso"},
        ],
        "muchasVeces": [
            {"tipo": "seguimiento_srt", "texto": "Seguimiento en SRT"},
            {"tipo": "control_documentacion", "texto": "Control de documentación"},
            {"tipo": "intimacion_hc", "texto": "Intimación a la ART por historia clínica"},
            {"tipo": "consulta_comision", "texto": "Consulta en comisión médica"},
        ],
    },
    2: {
        "unaVez": [
            {"tipo": "preparacion_equipo", "texto": "Preparación con equipo médico"},
        ],
        "muchasVeces": [
            {"tipo": "consulta_comision", "texto": "Consulta en Comisión Médica"},
            {"tipo": "seguimiento_turno", "texto": "Seguimiento de turno"},
            {"tipo": "control_expediente", "texto": "Control del expediente"},
            {"tipo": "revision_hc", "texto": "Revisión de historia clínica"},
        ],
    },
    3: {
        "unaVez": [
            {"tipo": "coordinacion_audiencia", "texto": "Coordinación de audiencia"},
        ],
        "muchasVeces": [
            {"tipo": "seguimiento_dictamen", "texto": "Seguimiento de dictamen"},
            {"tipo": "consulta_comision", "texto": "Consulta en comisión médica"},
            {"tipo": "analisis_caso", "texto": "Análisis del caso"},
            {"tipo": "vista_equipo", "texto": "Vista con equipo médico"},
        ],
    },
    4: {
        "unaVez": [
            {"tipo": "revision_dictamen", "texto": "Revisión de dictamen con equipo médico"},
            {"tipo": "impugnacion_dictamen", "texto": "Impugnación de dictamen con equipo médico"},
        ],
        "muchasVeces": [
            {"tipo": "seguimiento_resolucion", "texto": "Seguimiento de resolución"},
            {"tipo": "consulta_comision", "texto": "Consulta en comisión médica"},
            {"tipo": "control_notificaciones", "texto": "Control de notificaciones"},
        ],
    },
    5: None,  # Cobrado
}


# ============================================================
# GENERACIÓN DE SEGUIMIENTOS (misma lógica que portal-clientes)
# ============================================================

def es_feria_judicial(fecha: datetime) -> bool:
    mes = fecha.month
    dia = fecha.day
    if mes == 1:
        return True
    if mes == 7 and dia >= 16:
        return True
    return False


def seeded_random(seed: int, min_val: int, max_val: int, offset: int) -> int:
    """Pseudo-random determinístico, mismo algoritmo que el portal JS."""
    x = math.sin(seed + offset) * 10000
    frac = x - math.floor(x)
    return math.floor(frac * (max_val - min_val + 1)) + min_val


def obtener_config_seguimientos(etapa: int, es_srt: bool, es_despido: bool, estado_str: str):
    """Devuelve la config de seguimientos para la etapa, filtrando por condiciones."""
    if es_srt:
        config = SEGUIMIENTOS_SRT.get(etapa)
    elif es_despido:
        config = SEGUIMIENTOS_DESPIDO.get(etapa, SEGUIMIENTOS_DESPIDO.get(2))
    else:
        config = SEGUIMIENTOS_JUDICIAL.get(etapa, SEGUIMIENTOS_JUDICIAL.get(1))

    if config is None:
        return None

    # Filtrar requierePericia
    estados_con_pericia = ["19", "20", "21", "22", "23"]
    tiene_pericia = not es_srt and any(e in (estado_str or "") for e in estados_con_pericia)

    una_vez = [s for s in config.get("unaVez", []) if not s.get("requierePericia") or tiene_pericia]
    muchas_veces = [s for s in config.get("muchasVeces", []) if not s.get("requierePericia") or tiene_pericia]

    return {"unaVez": una_vez, "muchasVeces": muchas_veces}


def generar_seguimientos_para_rango(
    fecha_desde: datetime,
    fecha_hasta: datetime,
    caso_id: int,
    fechas_existentes: set,
    tipos_usados: set,
    estado_compartido: dict,
    etapa: int,
    es_srt: bool,
    es_despido: bool,
    estado_str: str,
) -> list:
    """Genera seguimientos automáticos para un rango de fechas con huecos."""
    seguimientos = []
    un_dia = timedelta(days=1)

    config = obtener_config_seguimientos(etapa, es_srt, es_despido, estado_str)
    if config is None:
        return seguimientos

    una_vez = config["unaVez"]
    muchas_veces = config["muchasVeces"]

    # Filtrar unaVez ya usados
    una_vez_disponibles = [s for s in una_vez if s["tipo"] not in tipos_usados]

    seed = caso_id or 1
    dias_inicio = seeded_random(seed, 8, 14, 0)
    fecha_actual = fecha_desde + timedelta(days=dias_inicio)
    idx = 0
    una_vez_idx = 0

    while fecha_actual < fecha_hasta and idx < 50:
        fecha_str = fecha_actual.strftime("%Y-%m-%d")

        # En SRT no aplica feria judicial
        saltar_feria = not es_srt and es_feria_judicial(fecha_actual)

        if not saltar_feria and fecha_str not in fechas_existentes:
            seg = None

            # Primero unaVez
            if una_vez_idx < len(una_vez_disponibles):
                seg = una_vez_disponibles[una_vez_idx]
                una_vez_idx += 1
                tipos_usados.add(seg["tipo"])
            # Después muchasVeces
            elif muchas_veces:
                seg_idx = seeded_random(seed, 0, len(muchas_veces) - 1, idx)
                seg = muchas_veces[seg_idx]

                # Evitar repetir el mismo que el anterior
                intentos = 0
                while seg["tipo"] == estado_compartido.get("ultimo_tipo") and len(muchas_veces) > 1 and intentos < len(muchas_veces):
                    seg_idx = (seg_idx + 1) % len(muchas_veces)
                    seg = muchas_veces[seg_idx]
                    intentos += 1

            if seg:
                estado_compartido["ultimo_tipo"] = seg["tipo"]
                seguimientos.append({
                    "fecha": fecha_str,
                    "tipo": seg["tipo"],
                    "descripcion": seg["texto"],
                })
                fechas_existentes.add(fecha_str)

        dias_sig = seeded_random(seed, 10, 18, idx + 100)
        fecha_actual = fecha_actual + timedelta(days=dias_sig)
        idx += 1

    return seguimientos


async def obtener_y_generar_movimientos(
    caso_id: int,
    estado_str: str,
    es_srt: bool,
    es_despido: bool,
    headers: dict,
    campo_id: str,
) -> list:
    """Obtiene movimientos reales + seguimientos guardados + genera nuevos para huecos."""
    movs_reales = []
    segs_guardados = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        # --- Movimientos reales ---
        if es_srt:
            # movimientos_srt
            try:
                resp = await client.get(
                    f"{SUPABASE_URL}/rest/v1/movimientos_srt",
                    headers=headers,
                    params={
                        "select": "fecha,tipo_descripcion",
                        "caso_srt_id": f"eq.{caso_id}",
                        "order": "fecha.desc",
                        "limit": "50",
                    },
                )
                if resp.status_code == 200:
                    for m in resp.json():
                        movs_reales.append({
                            "fecha": (m.get("fecha") or "")[:10],
                            "descripcion": traducir_movimiento("", m.get("tipo_descripcion", ""), es_srt=True),
                            "real": True,
                        })
            except Exception:
                pass
        else:
            # movimientos_pjn (CABA)
            try:
                resp = await client.get(
                    f"{SUPABASE_URL}/rest/v1/movimientos_pjn",
                    headers=headers,
                    params={
                        "select": "fecha,tipo,descripcion",
                        "expediente_id": f"eq.{caso_id}",
                        "order": "fecha.desc",
                        "limit": "50",
                    },
                )
                if resp.status_code == 200:
                    for m in resp.json():
                        movs_reales.append({
                            "fecha": (m.get("fecha") or "")[:10],
                            "descripcion": traducir_movimiento(m.get("tipo", ""), m.get("descripcion", "")),
                            "real": True,
                        })
            except Exception:
                pass

            # movimientos_judicial (Provincia/MEV)
            try:
                resp = await client.get(
                    f"{SUPABASE_URL}/rest/v1/movimientos_judicial",
                    headers=headers,
                    params={
                        "select": "fecha,tipo,descripcion",
                        "expediente_id": f"eq.{caso_id}",
                        "order": "fecha.desc",
                        "limit": "50",
                    },
                )
                if resp.status_code == 200:
                    for m in resp.json():
                        movs_reales.append({
                            "fecha": (m.get("fecha") or "")[:10],
                            "descripcion": traducir_movimiento(m.get("tipo", ""), m.get("descripcion", "")),
                            "real": True,
                        })
            except Exception:
                pass

        # --- Seguimientos ya guardados ---
        try:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/seguimientos_auto",
                headers=headers,
                params={
                    "select": "fecha,tipo,descripcion",
                    campo_id: f"eq.{caso_id}",
                    "order": "fecha.desc",
                },
            )
            if resp.status_code == 200:
                for s in resp.json():
                    segs_guardados.append({
                        "fecha": (s.get("fecha") or "")[:10],
                        "tipo": s.get("tipo", ""),
                        "descripcion": s.get("descripcion", ""),
                        "real": False,
                    })
        except Exception:
            pass

    # --- Filtrar movimientos sin fecha válida ---
    movs_reales = [m for m in movs_reales if m["fecha"] and len(m["fecha"]) >= 10]
    segs_guardados = [s for s in segs_guardados if s["fecha"] and len(s["fecha"]) >= 10]

    # --- Ordenar movimientos reales por fecha desc ---
    movs_reales.sort(key=lambda x: x["fecha"], reverse=True)

    # Fecha del primer movimiento (el más antiguo)
    fecha_primer_mov = None
    if movs_reales:
        try:
            fecha_primer_mov = datetime.strptime(movs_reales[-1]["fecha"], "%Y-%m-%d")
        except ValueError:
            pass

    # Filtrar seguimientos guardados anteriores al primer mov real
    if fecha_primer_mov:
        segs_guardados = [s for s in segs_guardados if s["fecha"] >= fecha_primer_mov.strftime("%Y-%m-%d")]

    # --- Preparar para generación ---
    fechas_existentes = set()
    for m in movs_reales:
        fechas_existentes.add(m["fecha"])
    for s in segs_guardados:
        fechas_existentes.add(s["fecha"])

    tipos_usados = set()
    for s in segs_guardados:
        if s.get("tipo"):
            tipos_usados.add(s["tipo"])

    etapa = extraer_etapa(estado_str)

    # Estado compartido entre llamadas
    segs_ord = sorted(segs_guardados, key=lambda x: x["fecha"], reverse=True)
    estado_compartido = {"ultimo_tipo": segs_ord[0]["tipo"] if segs_ord else None}

    nuevos_generados = []
    hoy = datetime.now()

    if movs_reales:
        # Hueco desde último movimiento hasta hoy (>12 días)
        try:
            ultima_fecha = datetime.strptime(movs_reales[0]["fecha"], "%Y-%m-%d")
            dias_desde_ultimo = (hoy - ultima_fecha).days
            if dias_desde_ultimo > 12:
                nuevos = generar_seguimientos_para_rango(
                    ultima_fecha, hoy, caso_id, fechas_existentes, tipos_usados,
                    estado_compartido, etapa, es_srt, es_despido, estado_str,
                )
                nuevos_generados.extend(nuevos)
        except ValueError:
            pass

        # Huecos entre movimientos reales (>30 días)
        for i in range(len(movs_reales) - 1):
            try:
                fecha_actual = datetime.strptime(movs_reales[i]["fecha"], "%Y-%m-%d")
                fecha_anterior = datetime.strptime(movs_reales[i + 1]["fecha"], "%Y-%m-%d")
                dias_entre = (fecha_actual - fecha_anterior).days
                if dias_entre > 30:
                    nuevos = generar_seguimientos_para_rango(
                        fecha_anterior, fecha_actual, caso_id, fechas_existentes, tipos_usados,
                        estado_compartido, etapa, es_srt, es_despido, estado_str,
                    )
                    nuevos_generados.extend(nuevos)
            except ValueError:
                pass
    elif not segs_guardados:
        # Sin movimientos reales NI seguimientos guardados: generar para los últimos 90 días
        fecha_inicio = hoy - timedelta(days=90)
        nuevos = generar_seguimientos_para_rango(
            fecha_inicio, hoy, caso_id, fechas_existentes, tipos_usados,
            estado_compartido, etapa, es_srt, es_despido, estado_str,
        )
        nuevos_generados.extend(nuevos)

    # --- Guardar nuevos en Supabase (fire & forget) ---
    if nuevos_generados:
        try:
            datos = []
            for s in nuevos_generados:
                registro = {
                    campo_id: caso_id,
                    "fecha": s["fecha"],
                    "tipo": s["tipo"],
                    "descripcion": s["descripcion"],
                }
                datos.append(registro)

            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{SUPABASE_URL}/rest/v1/seguimientos_auto",
                    headers={
                        **headers,
                        "Content-Type": "application/json",
                        "Prefer": "resolution=ignore-duplicates",
                    },
                    content=json.dumps(datos),
                )
        except Exception:
            pass

    # --- Combinar todo ---
    todos = []
    for m in movs_reales:
        todos.append({"fecha": m["fecha"], "descripcion": m["descripcion"], "tipo_entrada": "judicial" if not es_srt else "srt"})
    for s in segs_guardados:
        todos.append({"fecha": s["fecha"], "descripcion": s["descripcion"], "tipo_entrada": "estudio"})
    for s in nuevos_generados:
        todos.append({"fecha": s["fecha"], "descripcion": s["descripcion"], "tipo_entrada": "estudio"})

    # Ordenar por fecha desc
    todos.sort(key=lambda x: x["fecha"], reverse=True)

    # Filtrar repetidos consecutivos del estudio
    filtrados = []
    for item in todos:
        if item["tipo_entrada"] != "estudio":
            filtrados.append(item)
        elif not filtrados or filtrados[-1].get("descripcion") != item["descripcion"]:
            filtrados.append(item)

    return filtrados[:20]


# ============================================================
# TOOLS MCP
# ============================================================

@mcp.tool()
async def buscar_caso(nombre: str) -> str:
    """Busca el caso de un cliente por su nombre completo en la base de expedientes legales.
    Devuelve la caratula, el estado actual y un ID de referencia.
    IMPORTANTE: Solo compartir con el cliente la caratula y el estado del caso.
    Explicarle al cliente en que consiste ese estado en terminos simples.
    No revelar numero de expediente, juzgado ni datos internos.

    Args:
        nombre: Nombre completo o parcial del cliente (ej: "Perez Juan")
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return json.dumps({"error": "Variables de entorno SUPABASE_URL o SUPABASE_KEY no configuradas."})

    palabras = nombre.strip().split()
    if not palabras:
        return json.dumps({"error": "Debe proporcionar un nombre para buscar."})

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    url = f"{SUPABASE_URL}/rest/v1/expedientes"
    select = "id,caratula,estado"

    params = {"select": select, "limit": "5"}
    if len(palabras) == 1:
        params["caratula"] = f"ilike.%{palabras[0]}%"
    else:
        conditions = ",".join([f"caratula.ilike.%{p}%" for p in palabras])
        params["and"] = f"({conditions})"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
    except Exception as e:
        return json.dumps({"error": f"No se pudo conectar a Supabase: {type(e).__name__}: {str(e)}"})

    if response.status_code != 200:
        return json.dumps({"error": f"Error al consultar Supabase: {response.status_code}", "detalle": response.text})

    resultados = response.json()

    if not resultados:
        return json.dumps({
            "mensaje": f"No se encontraron casos para '{nombre}'.",
            "sugerencia": "Verificar que el nombre esté bien escrito o probar con el apellido solamente.",
        })

    casos = []
    for r in resultados:
        casos.append({
            "expediente_id": r.get("id", ""),
            "caratula": r.get("caratula", ""),
            "estado": r.get("estado", "Sin estado registrado"),
        })

    return json.dumps({"cantidad_resultados": len(casos), "casos": casos}, ensure_ascii=False)


@mcp.tool()
async def buscar_caso_srt(nombre: str) -> str:
    """Busca el caso de un cliente en comision medica (SRT/etapa administrativa).
    Usar este tool cuando el caso NO se encuentra en la tabla de expedientes judiciales,
    ya que puede estar todavia en etapa administrativa ante la SRT.
    Devuelve el estado del caso en la SRT y las ultimas comunicaciones.
    IMPORTANTE: Solo compartir con el cliente la etapa y las novedades relevantes.
    No revelar datos internos ni numeros de expediente SRT.

    Args:
        nombre: Nombre completo o parcial del cliente (ej: "Perez Juan")
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return json.dumps({"error": "Variables de entorno no configuradas."})

    palabras = nombre.strip().split()
    if not palabras:
        return json.dumps({"error": "Debe proporcionar un nombre para buscar."})

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    url_srt = f"{SUPABASE_URL}/rest/v1/casos_srt"
    select_srt = "id,nombre,etapa,estado,numero_srt,comision_medica"
    params = {"select": select_srt, "limit": "5", "activo": "eq.true"}
    if len(palabras) == 1:
        params["nombre"] = f"ilike.%{palabras[0]}%"
    else:
        conditions = ",".join([f"nombre.ilike.%{p}%" for p in palabras])
        params["and"] = f"({conditions})"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url_srt, headers=headers, params=params)
    except Exception as e:
        return json.dumps({"error": f"No se pudo conectar a Supabase: {str(e)}"})

    if response.status_code != 200:
        return json.dumps({"error": f"Error Supabase: {response.status_code}"})

    resultados = response.json()

    if not resultados:
        return json.dumps({"mensaje": f"No se encontraron casos SRT para '{nombre}'."})

    casos = []
    for r in resultados:
        caso = {
            "caso_srt_id": r.get("id", ""),
            "nombre": r.get("nombre", ""),
            "etapa": r.get("etapa", "Sin etapa"),
            "estado": r.get("estado", ""),
            "comision_medica": r.get("comision_medica", ""),
        }

        caso_id = r.get("id")
        numero_srt = r.get("numero_srt", "")
        comunicaciones = []

        if caso_id:
            url_com_srt = f"{SUPABASE_URL}/rest/v1/comunicaciones_srt"
            params_com = {
                "select": "fecha_notificacion,tipo_comunicacion,detalle,estado",
                "caso_srt_id": f"eq.{caso_id}",
                "order": "fecha_notificacion.desc",
                "limit": "3",
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp_com = await client.get(url_com_srt, headers=headers, params=params_com)
                if resp_com.status_code == 200:
                    for c in resp_com.json():
                        comunicaciones.append({
                            "fecha": c.get("fecha_notificacion", ""),
                            "tipo": c.get("tipo_comunicacion", ""),
                            "detalle": c.get("detalle", ""),
                            "origen": "SRT",
                        })
            except Exception:
                pass

        if numero_srt:
            url_com_mv = f"{SUPABASE_URL}/rest/v1/comunicaciones_miventanilla"
            params_mv = {
                "select": "fecha_notificacion,tipo_comunicacion,detalle,estado",
                "srt_expediente_nro": f"eq.{numero_srt}",
                "order": "fecha_notificacion.desc",
                "limit": "3",
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp_mv = await client.get(url_com_mv, headers=headers, params=params_mv)
                if resp_mv.status_code == 200:
                    for c in resp_mv.json():
                        comunicaciones.append({
                            "fecha": c.get("fecha_notificacion", ""),
                            "tipo": c.get("tipo_comunicacion", ""),
                            "detalle": c.get("detalle", ""),
                            "origen": "Mi Ventanilla",
                        })
            except Exception:
                pass

        if comunicaciones:
            caso["ultimas_comunicaciones"] = comunicaciones
        casos.append(caso)

    return json.dumps({"cantidad_resultados": len(casos), "casos": casos}, ensure_ascii=False)


@mcp.tool()
async def consultar_movimientos(expediente_id: int) -> str:
    """Consulta los ultimos movimientos de un expediente judicial.
    Usar DESPUES de buscar_caso, pasando el expediente_id que devolvio.
    Devuelve movimientos reales del juzgado y seguimientos del estudio, todo traducido.
    IMPORTANTE: Mostrar al cliente los movimientos tal cual. NO inventar movimientos.

    Args:
        expediente_id: ID numerico del expediente (obtenido de buscar_caso)
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return json.dumps({"error": "Variables de entorno no configuradas."})

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    # Obtener estado y tipo_caso del expediente
    estado_str = ""
    es_despido = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Intentar con tipo_caso primero
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/expedientes",
                headers=headers,
                params={
                    "select": "estado,tipo_caso",
                    "id": f"eq.{expediente_id}",
                    "limit": "1",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    estado_str = data[0].get("estado", "")
                    es_despido = (data[0].get("tipo_caso") or "").lower() == "despido"
            else:
                # Si tipo_caso no existe, intentar solo estado
                resp2 = await client.get(
                    f"{SUPABASE_URL}/rest/v1/expedientes",
                    headers=headers,
                    params={
                        "select": "estado",
                        "id": f"eq.{expediente_id}",
                        "limit": "1",
                    },
                )
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    if data2:
                        estado_str = data2[0].get("estado", "")
    except Exception:
        pass

    try:
        movimientos = await obtener_y_generar_movimientos(
            caso_id=expediente_id,
            estado_str=estado_str,
            es_srt=False,
            es_despido=es_despido,
            headers=headers,
            campo_id="expediente_id",
        )
    except Exception as e:
        return json.dumps({"error": f"Error al consultar movimientos: {str(e)}"})

    if not movimientos:
        return json.dumps({"mensaje": "No se encontraron movimientos para este expediente."})

    return json.dumps({
        "expediente_id": expediente_id,
        "total_movimientos": len(movimientos),
        "movimientos": movimientos,
    }, ensure_ascii=False)


@mcp.tool()
async def consultar_movimientos_srt(caso_srt_id: int) -> str:
    """Consulta los ultimos movimientos de un caso SRT (comision medica).
    Usar DESPUES de buscar_caso_srt, pasando el caso_srt_id que devolvio.
    Devuelve movimientos reales de la SRT y seguimientos del estudio, todo traducido.
    IMPORTANTE: Mostrar al cliente los movimientos tal cual. NO inventar movimientos.

    Args:
        caso_srt_id: ID numerico del caso SRT (obtenido de buscar_caso_srt)
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return json.dumps({"error": "Variables de entorno no configuradas."})

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    # Obtener estado del caso SRT
    estado_str = ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/casos_srt",
                headers=headers,
                params={
                    "select": "estado",
                    "id": f"eq.{caso_srt_id}",
                    "limit": "1",
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    estado_str = data[0].get("estado", "")
    except Exception:
        pass

    try:
        movimientos = await obtener_y_generar_movimientos(
            caso_id=caso_srt_id,
            estado_str=estado_str,
            es_srt=True,
            es_despido=False,
            headers=headers,
            campo_id="caso_srt_id",
        )
    except Exception as e:
        return json.dumps({"error": f"Error al consultar movimientos SRT: {str(e)}"})

    if not movimientos:
        return json.dumps({"mensaje": "No se encontraron movimientos para este caso SRT."})

    return json.dumps({
        "caso_srt_id": caso_srt_id,
        "total_movimientos": len(movimientos),
        "movimientos": movimientos,
    }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=PORT, path="/mcp")
