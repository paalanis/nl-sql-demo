import os
from anthropic import Anthropic
from nl_to_sql.prompt import SYSTEM_PROMPT
from nl_to_sql.db import execute_query

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def generate_sql(query_text: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": query_text}]
    )
    return response.content[0].text.strip()


def format_results(query_text: str, sql: str, results: list) -> str:
    if not results:
        return "No encontré datos para esa consulta."

    rows_text = "\n".join(str(row) for row in results[:20])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system="Eres un asistente de negocio. Respondé en español, de forma clara y concisa, sin tecnicismos. Usá emojis cuando sea apropiado.",
        messages=[{
            "role": "user",
            "content": f"El usuario preguntó: {query_text}\n\nLos datos obtenidos son:\n{rows_text}\n\nRespondé la pregunta del usuario con estos datos."
        }]
    )
    return response.content[0].text.strip()


def run_pipeline(query_text: str) -> str:
    print(f"[PIPELINE] Generando SQL para: {query_text}")
    sql = generate_sql(query_text)
    print(f"[PIPELINE] SQL generado: {sql}")

    if sql == "NO_QUERY":
        return "No pude entender tu consulta. Intentá preguntar sobre ventas, productos, empleados, stock o turnos."

    results = execute_query(sql)
    print(f"[PIPELINE] Resultados: {len(results)} filas")

    return format_results(query_text, sql, results)