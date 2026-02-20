import os
import json
import httpx
from fastmcp import FastMCP
from fastmcp.server.auth import BearerTokenAuth
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

# --- Config ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
MCP_AUTH_TOKEN = os.environ["MCP_AUTH_TOKEN"]
PORT = int(os.environ.get("PORT", 8000))

# --- Auth ---
auth = BearerTokenAuth(token=MCP_AUTH_TOKEN)

# --- MCP Server ---
mcp = FastMCP(
    "Expedientes Legales",
    instructions="Server MCP para buscar el estado de expedientes legales en un estudio de abogados laborales.",
    auth=auth,
)


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

    # Construir filtros ilike por cada palabra del nombre
    filters = [f"caratula.ilike.%{palabra}%" for palabra in palabras]

    url = f"{SUPABASE_URL}/rest/v1/expedientes"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    # Construir query: si es una palabra, filtro directo; si son varias, usar AND
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


# --- CORS middleware para OpenAI ---
cors_middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
]

# --- ASGI app (para produccion con uvicorn) ---
app = mcp.http_app(path="/mcp", middleware=cors_middleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
