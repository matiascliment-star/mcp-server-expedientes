import os
import json
import httpx
from fastmcp import FastMCP

# --- Config (strip para evitar espacios/newlines ocultos) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
PORT = int(os.environ.get("PORT", 8000))

# --- MCP Server ---
mcp = FastMCP("Expedientes Legales")


@mcp.tool()
async def buscar_caso(nombre: str) -> str:
    """Busca el caso de un cliente por su nombre completo.
    Devuelve la caratula y el estado actual del expediente.

    Args:
        nombre: Nombre completo o parcial del cliente (ej: "Perez Juan")
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return json.dumps({"error": "Variables de entorno SUPABASE_URL o SUPABASE_KEY no configuradas."})

    palabras = nombre.strip().split()
    if not palabras:
        return json.dumps({"error": "Debe proporcionar un nombre para buscar."})

    filters = [f"caratula.ilike.%{palabra}%" for palabra in palabras]

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    if len(filters) == 1:
        full_url = f"{SUPABASE_URL}/rest/v1/expedientes?select=*&caratula=ilike.%25{palabras[0]}%25&limit=5"
    else:
        conditions = ",".join(filters)
        full_url = f"{SUPABASE_URL}/rest/v1/expedientes?select=*&and=({conditions})&limit=5"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url, headers=headers)
    except Exception as e:
        return json.dumps({
            "error": f"No se pudo conectar a Supabase: {type(e).__name__}: {str(e)}",
            "url_used": full_url[:60] + "...",
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
        caso = {
            "caratula": r.get("caratula", ""),
            "estado": r.get("estado", "Sin estado registrado"),
        }
        if r.get("juzgado"):
            caso["juzgado"] = r["juzgado"]
        if r.get("expediente_nro"):
            caso["expediente_nro"] = r["expediente_nro"]
        if r.get("fecha_inicio"):
            caso["fecha_inicio"] = r["fecha_inicio"]
        casos.append(caso)

    return json.dumps({
        "cantidad_resultados": len(casos),
        "casos": casos,
    }, ensure_ascii=False)


@mcp.tool()
async def debug_config() -> str:
    """Muestra si las variables de entorno estan configuradas y prueba la conexion a Supabase."""
    result = {
        "SUPABASE_URL_configured": bool(SUPABASE_URL),
        "SUPABASE_URL_preview": SUPABASE_URL[:50] + "..." if SUPABASE_URL else "(empty)",
        "SUPABASE_URL_length": len(SUPABASE_URL),
        "SUPABASE_URL_repr": repr(SUPABASE_URL[:50]),
        "SUPABASE_KEY_configured": bool(SUPABASE_KEY),
        "PORT": PORT,
    }
    # Probar conexion a Supabase
    if SUPABASE_URL:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{SUPABASE_URL}/rest/v1/", headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                })
                result["supabase_connection"] = f"OK - status {resp.status_code}"
        except Exception as e:
            result["supabase_connection"] = f"FAILED - {type(e).__name__}: {str(e)}"
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=PORT, path="/mcp")
