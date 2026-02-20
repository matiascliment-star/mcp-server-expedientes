# Instrucciones para Claude Code - MCP Server para Supabase

## Objetivo
Crear un MCP server remoto que OpenAI pueda consumir desde la Responses API. El server debe exponer un tool que busque casos legales en Supabase y devuelva el estado del caso.

## Contexto
Soy un estudio de abogados laborales. Tenemos un bot de WhatsApp (Sofía) que usa OpenAI Responses API. Los clientes escriben para saber el estado de su caso. Hoy usamos un TXT estático como base de datos, pero queremos que consulte Supabase en tiempo real via MCP.

## Stack
- **MCP server**: Python con FastMCP (preferido) o Node.js
- **Base de datos**: Supabase (PostgreSQL)
- **Deploy**: Railway (preferido), Render, o Fly.io — necesito URL pública con HTTPS
- **Transporte**: Streamable HTTP (para compatibilidad con OpenAI Responses API)

## Datos de Supabase
- **URL del proyecto**: [REEMPLAZAR con tu URL, ej: https://xxxxx.supabase.co]
- **API Key (anon/service_role)**: [REEMPLAZAR con tu key]
- **Tabla**: `expedientes`
- **Columnas relevantes**:
  - `caratula`: texto que contiene el nombre del cliente y la demanda (ej: "PEREZ JUAN CARLOS C/ EMPRESA S.A. S/ ACCIDENTE DE TRABAJO")
  - `estado`: texto con el estado actual del caso (ej: "En trámite", "Pericia médica pendiente", etc.)
  - Si hay otras columnas útiles como `juzgado`, `expediente_nro`, `fecha_inicio`, incluirlas también en la respuesta

## Tool a exponer
- **Nombre**: `buscar_caso`
- **Descripción**: "Busca el caso de un cliente por su nombre completo. Devuelve la carátula y el estado actual del expediente."
- **Parámetro**: `nombre` (string) — el nombre que el cliente proporciona
- **Lógica de búsqueda**:
  - Búsqueda case-insensitive dentro del campo `caratula`
  - Usar `ilike` con el nombre buscado (ej: `caratula.ilike.%PEREZ%JUAN%`)
  - Separar el nombre en palabras y buscar que todas estén presentes en la carátula
  - Si hay múltiples resultados, devolver todos (máximo 5) para que el modelo desambigüe
  - Si no hay resultados, devolver un mensaje indicando que no se encontró el caso
- **Respuesta**: JSON con los campos del caso encontrado

## Seguridad
- Agregar autenticación al MCP server (Bearer token o API key en header)
- Las credenciales de Supabase deben estar en variables de entorno, no hardcodeadas
- El token de autenticación del MCP server también debe ser variable de entorno

## Requisitos técnicos
- El MCP server debe usar transporte **Streamable HTTP** (no stdio)
- Debe responder en el endpoint `/mcp` o `/mcp/`
- Debe implementar `tools/list` y `tools/call` del protocolo MCP
- Testear que el server funcione antes de deployar
- Configurar CORS si es necesario para que OpenAI pueda acceder

## Deploy
1. Crear el proyecto
2. Configurar variables de entorno (SUPABASE_URL, SUPABASE_KEY, MCP_AUTH_TOKEN)
3. Deployar a Railway con URL pública HTTPS
4. Darme la URL final para configurar en OpenAI

## Test
Una vez deployado, verificar que funcione con un curl como este:
```bash
curl -X POST https://[URL_DEL_SERVER]/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer [TOKEN]" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## Notas
- No necesito interfaz web ni frontend, solo el MCP server
- Si FastMCP no es viable, usar el SDK de MCP para Node.js/TypeScript
- Priorizar simplicidad y que funcione
