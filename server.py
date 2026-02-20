import os
import json
import httpx
from fastmcp import FastMCP

# --- Config (strip para evitar espacios/newlines ocultos) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
PORT = int(os.environ.get("PORT", 8000))

# --- MCP Server ---
mcp = FastMCP("Expedientes Legales", stateless_http=True, json_response=True)


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

    # Usar httpx params para que codifique correctamente los %
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
        return json.dumps({
            "error": f"No se pudo conectar a Supabase: {type(e).__name__}: {str(e)}",
        })

    if response.status_code != 200:
        return json.dumps({
            "error": f"Error al consultar Supabase: {response.status_code}",
            "detalle": response.text,
        })

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

    return json.dumps({
        "cantidad_resultados": len(casos),
        "casos": casos,
    }, ensure_ascii=False)



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

    # Buscar en casos_srt por nombre
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
        return json.dumps({
            "mensaje": f"No se encontraron casos SRT para '{nombre}'.",
        })

    casos = []
    for r in resultados:
        caso = {
            "caso_srt_id": r.get("id", ""),
            "nombre": r.get("nombre", ""),
            "etapa": r.get("etapa", "Sin etapa"),
            "estado": r.get("estado", ""),
            "comision_medica": r.get("comision_medica", ""),
        }

        # Buscar comunicaciones recientes de este caso
        caso_id = r.get("id")
        numero_srt = r.get("numero_srt", "")
        comunicaciones = []

        # Comunicaciones SRT
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

        # Comunicaciones Mi Ventanilla
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

    return json.dumps({
        "cantidad_resultados": len(casos),
        "casos": casos,
    }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=PORT, path="/mcp")
