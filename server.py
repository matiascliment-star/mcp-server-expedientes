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

    filters = [f"caratula.ilike.%{palabra}%" for palabra in palabras]

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    # Solo pedir las columnas necesarias: id, caratula, estado
    select = "id,caratula,estado"

    if len(filters) == 1:
        full_url = f"{SUPABASE_URL}/rest/v1/expedientes?select={select}&caratula=ilike.%25{palabras[0]}%25&limit=5"
    else:
        conditions = ",".join(filters)
        full_url = f"{SUPABASE_URL}/rest/v1/expedientes?select={select}&and=({conditions})&limit=5"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url, headers=headers)
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



if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=PORT, path="/mcp")
