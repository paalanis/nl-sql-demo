import os
from anthropic import Anthropic
from nl_to_sql.prompt import SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT
from nl_to_sql.db import execute_query

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def generate_sql(query_text: str, history: list) -> str:
    messages = history + [{"role": "user", "content": query_text}]
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text.strip()


def generate_chat_response(query_text: str, history: list) -> str:
    messages = history + [{"role": "user", "content": query_text}]
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system=CHAT_SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text.strip()


def format_results(query_text: str, sql: str, results: list) -> str:
    if not results:
        return "No encontré datos para esa consulta. Verificá el período o los filtros que usaste."

    rows_text = "\n".join(str(row) for row in results[:100])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=(
            "Eres un asistente de negocio para WhatsApp. "
            "Respondé en español con formato limpio y estructurado.\n\n"
            "REGLAS DE DATOS — MUY IMPORTANTE:\n"
            "- Usá ÚNICAMENTE los datos que te proveo, sin excepción.\n"
            "- NUNCA inventes, inferiras ni expliques ausencias de datos.\n"
            "- NUNCA digas 'datos parciales', 'corte', 'solo algunas sucursales' ni nada similar.\n"
            "- Si los datos están completos, presentalos. Si no hay datos, no hay datos.\n\n"
            "REGLAS DE FORMATO:\n"
            "- Empezá con una línea de encabezado: emoji + tema en *negrita*\n"
            "- Usá saltos de línea para separar secciones\n"
            "- Usá viñetas con • para listar ítems\n"
            "- Usá *texto* para resaltar valores importantes (un solo asterisco)\n"
            "- NUNCA uses ** doble asterisco\n"
            "- NUNCA uses markdown como #, ##, -, ---\n"
            "- Máximo 8 líneas en total\n"
            "- Solo números concretos, sin frases de relleno\n"
            "- No hagas preguntas ni recomendaciones\n\n"
            "EJEMPLO de respuesta bien formateada:\n"
            "👥 *Empleados por rol*\n\n"
            "• Cocina: *8*\n"
            "• Cajeros: *4*\n"
            "• Gerentes: *4*\n\n"
            "*Total: 16 empleados* en 4 sucursales"
        ),
        messages=[{
            "role": "user",
            "content": f"El usuario preguntó: {query_text}\n\nDatos:\n{rows_text}\n\nRespondé con el formato indicado."
        }]
    )
    return response.content[0].text.strip()


def run_pipeline(query_text: str, history: list = []) -> str:
    print(f"[PIPELINE] Generando SQL para: {query_text}")
    sql = generate_sql(query_text, history)
    print(f"[PIPELINE] SQL generado: {sql}")

    if sql == "GREETING":
        return (
            "¡Hola! 👋 Soy el asistente de *BurgerDemo*.\n\n"
            "Puedo consultarte info sobre ventas, productos, stock, empleados y sucursales.\n\n"
            "¿Qué querés saber?"
        )

    if sql == "HELP":
        return (
            "📋 *Esto es lo que puedo consultar:*\n\n"
            "📊 *Ventas* — totales por fecha, sucursal o producto\n"
            "🍔 *Productos* — precios, costos y categorías\n"
            "👥 *Empleados* — roles, turnos y horas trabajadas\n"
            "📦 *Stock* — disponibilidad por sucursal\n"
            "🏪 *Sucursales* — Centro, Confluencia, Alta Barda y Cipolletti\n\n"
            "Escribime en lenguaje natural. 💬"
        )

    if sql == "NO_QUERY":
        return (
            "No encontré datos para eso en el sistema. 🤔\n\n"
            "Puedo ayudarte con ventas, productos, stock, empleados y sucursales.\n\n"
            "¿Querés intentar con otra consulta?"
        )

    if sql == "CHAT":
        print(f"[PIPELINE] Modo conversacional")
        return generate_chat_response(query_text, history)

    results = execute_query(sql)
    print(f"[PIPELINE] Resultados: {len(results)} filas")

    return format_results(query_text, sql, results)
