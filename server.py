import os
import json
import httpx
from fastmcp import FastMCP

# --- Config ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
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
    palabras = nombre.strip().split()
    if not palabras:
        return json.dumps({"error": "Debe proporcionar un nombre para buscar."})

    filters = [f"caratula.ilike.%{palabra}%" for palabra in palabras]

    url = f"{SUPABASE_URL}/rest/v1/expedientes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    if len(filters) == 1:
        full_url = f"{url}?select=*&caratula=ilike.%25{palabras[0]}%25&limit=5"
    else:
        conditions = ",".join(filters)
        full_url = f"{url}?select=*&and=({conditions})&limit=5"

    async with httpx.AsyncClient() as client:
        response = await client.get(full_url, headers=headers)

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
    """Muestra si las variables de entorno estan configuradas (sin revelar valores completos)."""
    url_set = bool(SUPABASE_URL)
    key_set = bool(SUPABASE_KEY)
    return json.dumps({
        "SUPABASE_URL_configured": url_set,
        "SUPABASE_URL_preview": SUPABASE_URL[:30] + "..." if url_set else "(empty)",
        "SUPABASE_KEY_configured": key_set,
        "PORT": PORT,
    })


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=PORT, path="/mcp")
