import os
from anthropic import Anthropic
from nl_to_sql.prompt import SYSTEM_PROMPT
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


def format_results(query_text: str, sql: str, results: list) -> str:
    if not results:
        return "No encontré datos para esa consulta. Verificá el período o los filtros que usaste."

    rows_text = "\n".join(str(row) for row in results[:20])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=(
            "Eres un asistente de negocio conciso. "
            "Respondé en español, en 2-3 líneas máximo. "
            "Usá números concretos y emojis cuando sea apropiado. "
            "No des recomendaciones ni hagas preguntas adicionales."
        ),
        messages=[{
            "role": "user",
            "content": f"El usuario preguntó: {query_text}\n\nDatos:\n{rows_text}\n\nRespondé la pregunta con estos datos en 2-3 líneas."
        }]
    )
    return response.content[0].text.strip()


def run_pipeline(query_text: str, history: list = []) -> str:
    print(f"[PIPELINE] Generando SQL para: {query_text}")
    sql = generate_sql(query_text, history)
    print(f"[PIPELINE] SQL generado: {sql}")

    if sql == "NO_QUERY":
        return "No pude entender tu consulta. Podés preguntarme sobre ventas, productos, empleados, stock o turnos. 😊"

    if sql == "META_QUERY":
        return (
            "Puedo consultarte información sobre:\n\n"
            "📊 *Ventas* — totales por fecha, sucursal o producto\n"
            "🍔 *Productos* — precios, costos, categorías\n"
            "👥 *Empleados* — roles, turnos y horas trabajadas\n"
            "📦 *Stock* — cantidades disponibles por sucursal\n"
            "🏪 *Sucursales* — Centro, Confluencia, Alta Barda y Cipolletti\n\n"
            "Preguntame lo que necesites en lenguaje natural. 🙌"
        )

    results = execute_query(sql)
    print(f"[PIPELINE] Resultados: {len(results)} filas")

    return format_results(query_text, sql, results)