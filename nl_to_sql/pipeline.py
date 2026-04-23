"""
Pipeline de procesamiento de mensajes para BurgerDemo.

Arquitectura:
  1) classify_and_rewrite() — Haiku. Decide intent + reescribe followups.
  2) generate_sql()         — Sonnet. Solo genera SQL, no ve historial.
  3) format_results()       — Sonnet. Da formato WhatsApp a los resultados.

run_pipeline() orquesta todo y devuelve (response_text, history_entry)
para que el worker persista el turno estructurado en Redis.
"""

import json
import logging
import os
from typing import Optional, Tuple

from anthropic import Anthropic

from nl_to_sql.db import execute_query
from nl_to_sql.prompts import (
    CHAT_REPLIES,
    CLASSIFIER_PROMPT,
    FORMAT_PROMPT,
    SQL_GEN_PROMPT,
)

logger = logging.getLogger(__name__)

# ---------- Configuración por env var -------------------------------------

CLASSIFIER_MODEL = os.environ.get("CLASSIFIER_MODEL", "claude-haiku-4-5")
SQL_MODEL = os.environ.get("SQL_MODEL", "claude-sonnet-4-6")
FORMAT_MODEL = os.environ.get("FORMAT_MODEL", "claude-sonnet-4-6")
CONFIDENCE_THRESHOLD = float(os.environ.get("CLASSIFIER_CONFIDENCE_THRESHOLD", "0.6"))

# Max tokens por llamada. Los defaults son los que ya usábamos.
#   CLASSIFIER: el JSON del clasificador es chico (~150 tokens). 300 da margen.
#   SQL: una query SQL larga con JOINs y CTEs puede pasar los 400. 500 es seguro.
#   FORMAT: respuesta WhatsApp, máximo 8 líneas. 400 alcanza de sobra.
CLASSIFIER_MAX_TOKENS = int(os.environ.get("CLASSIFIER_MAX_TOKENS", "300"))
SQL_MAX_TOKENS = int(os.environ.get("SQL_MAX_TOKENS", "500"))
FORMAT_MAX_TOKENS = int(os.environ.get("FORMAT_MAX_TOKENS", "400"))

# Intents que NO necesitan SQL — respondemos con texto canned.
CHAT_INTENTS = {"GREETING", "HELP", "OUT_OF_SCOPE", "CHAT_ACK", "CHAT_CORRECTION"}
SQL_INTENTS = {"NEW_QUERY", "FOLLOWUP_QUERY"}
ALL_INTENTS = CHAT_INTENTS | SQL_INTENTS

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------- Paso 1: clasificar + reescribir -------------------------------

def classify_and_rewrite(query_text: str, history: list) -> dict:
    """
    Llama a Haiku con el mensaje del usuario y el historial estructurado.
    Devuelve un dict: {intent, confidence, reasoning, rewritten_query}.

    Si el modelo devuelve algo que no parsea, retornamos un dict "degradado"
    con confidence=0.0 para que el pipeline pida reformulación.
    """
    user_block = {
        "current_message": query_text,
        "history": history or [],
    }

    response = client.messages.create(
        model=CLASSIFIER_MODEL,
        max_tokens=CLASSIFIER_MAX_TOKENS,
        system=CLASSIFIER_PROMPT,
        messages=[{
            "role": "user",
            "content": json.dumps(user_block, ensure_ascii=False),
        }],
    )
    raw = response.content[0].text.strip()

    # Defensa: a veces los modelos envuelven el JSON en ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("[CLASSIFIER] JSON inválido: %s | raw=%r", e, raw)
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "reasoning": f"No pude parsear la salida del clasificador: {e}",
            "rewritten_query": None,
        }

    # Normalización defensiva: asegurar que todos los campos estén presentes
    # y con el tipo correcto. Si falta algo, degradamos confidence.
    intent = parsed.get("intent", "UNKNOWN")
    if intent not in ALL_INTENTS:
        logger.warning("[CLASSIFIER] intent desconocido: %r", intent)
        return {
            "intent": "UNKNOWN",
            "confidence": 0.0,
            "reasoning": f"Intent no reconocido: {intent}",
            "rewritten_query": None,
        }

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "intent": intent,
        "confidence": max(0.0, min(1.0, confidence)),
        "reasoning": str(parsed.get("reasoning", "")),
        "rewritten_query": parsed.get("rewritten_query") or None,
    }


# ---------- Paso 2: generar SQL -------------------------------------------

def generate_sql(query_text: str) -> str:
    """
    Genera SQL para una query YA autocontenida. No recibe historial.
    Puede devolver 'NO_QUERY' si el modelo considera que no se puede resolver.
    """
    response = client.messages.create(
        model=SQL_MODEL,
        max_tokens=SQL_MAX_TOKENS,
        system=SQL_GEN_PROMPT,
        messages=[{"role": "user", "content": query_text}],
    )
    sql = response.content[0].text.strip()

    # Defensa contra fences accidentales
    if sql.startswith("```"):
        sql = sql.strip("`")
        for prefix in ("sql\n", "mysql\n"):
            if sql.lower().startswith(prefix):
                sql = sql[len(prefix):]
                break
        sql = sql.strip()

    return sql


# ---------- Paso 3: formatear resultados ----------------------------------

def format_results(query_text: str, results: list) -> str:
    if not results:
        return "No encontré datos para esa consulta. Verificá el período o los filtros que usaste."

    rows_text = "\n".join(str(row) for row in results[:100])

    response = client.messages.create(
        model=FORMAT_MODEL,
        max_tokens=FORMAT_MAX_TOKENS,
        system=FORMAT_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"El usuario preguntó: {query_text}\n\n"
                f"Datos:\n{rows_text}\n\n"
                "Respondé con el formato indicado."
            ),
        }],
    )
    return response.content[0].text.strip()


# ---------- Construcción del turno estructurado ---------------------------

def _make_history_entry(
    user_message: str,
    intent: str,
    sql: Optional[str] = None,
    row_count: Optional[int] = None,
    result_summary: str = "",
) -> dict:
    """
    Turno estructurado que se guarda en Redis. Esto es lo que el clasificador
    va a ver como historial en el próximo mensaje. NO contiene texto
    formateado con emojis — solo datos que ayudan a desambiguar.
    """
    return {
        "user_message": user_message,
        "intent": intent,
        "sql": sql,
        "row_count": row_count,
        "result_summary": result_summary,
    }


def _summarize_results(results: list) -> str:
    """
    Resumen ultra-breve de los resultados para dejarlo en el historial.
    No es la respuesta al usuario; es el recordatorio que el clasificador
    va a leer para resolver referencias ("las otras", "el anterior").
    """
    if not results:
        return "sin datos"
    if len(results) == 1:
        # Caso típico: un SUM agregado. Mostramos el dict compacto.
        return str(results[0])[:200]
    return f"{len(results)} filas. Primera: {str(results[0])[:150]}"


# ---------- Orquestación --------------------------------------------------

def run_pipeline(query_text: str, history: list) -> Tuple[str, dict]:
    """
    Procesa un mensaje del usuario y devuelve:
      - response_text: lo que se manda por WhatsApp.
      - history_entry: dict estructurado para guardar en Redis.

    El worker es responsable de persistir history_entry; el pipeline no
    toca Redis directamente.
    """
    logger.info("[PIPELINE] Mensaje: %r", query_text)

    # --- 1) Clasificar + reescribir
    classification = classify_and_rewrite(query_text, history)
    intent = classification["intent"]
    confidence = classification["confidence"]
    logger.info(
        "[PIPELINE] intent=%s confidence=%.2f reasoning=%s",
        intent, confidence, classification["reasoning"],
    )

    # --- 2) Confidence bajo → pedir reformulación
    if confidence < CONFIDENCE_THRESHOLD:
        logger.info(
            "[PIPELINE] confidence %.2f < umbral %.2f — pidiendo reformulación",
            confidence, CONFIDENCE_THRESHOLD,
        )
        return (
            CHAT_REPLIES["LOW_CONFIDENCE"],
            _make_history_entry(
                user_message=query_text,
                intent="LOW_CONFIDENCE",
                result_summary=f"confidence={confidence:.2f}",
            ),
        )

    # --- 3) Intents chat → respuesta canned, no hay SQL
    if intent in CHAT_INTENTS:
        return (
            CHAT_REPLIES[intent],
            _make_history_entry(user_message=query_text, intent=intent),
        )

    # --- 4) Intents SQL → generar, ejecutar, formatear
    query_for_sql = classification["rewritten_query"] or query_text
    logger.info("[PIPELINE] Query para SQL: %r", query_for_sql)

    sql = generate_sql(query_for_sql)
    logger.info("[PIPELINE] SQL: %s", sql)

    if sql == "NO_QUERY":
        return (
            CHAT_REPLIES["OUT_OF_SCOPE"],
            _make_history_entry(
                user_message=query_text,
                intent="OUT_OF_SCOPE",
                result_summary="NO_QUERY desde generador SQL",
            ),
        )

    try:
        results = execute_query(sql)
    except Exception as exc:
        logger.exception("[PIPELINE] Error ejecutando SQL")
        return (
            "Tuve un problema ejecutando la consulta. ¿Podés reformular?",
            _make_history_entry(
                user_message=query_text,
                intent=intent,
                sql=sql,
                result_summary=f"ERROR: {exc.__class__.__name__}",
            ),
        )

    logger.info("[PIPELINE] Resultados: %d filas", len(results))
    response_text = format_results(query_for_sql, results)

    return (
        response_text,
        _make_history_entry(
            user_message=query_text,
            intent=intent,
            sql=sql,
            row_count=len(results),
            result_summary=_summarize_results(results),
        ),
    )
