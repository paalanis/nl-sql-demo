"""
Paquete de prompts de BurgerDemo.

Cada prompt vive en su propio submódulo para que edición y versionado
funcionen por separado. Este __init__ reexporta los nombres públicos
para que el resto del código pueda escribir:

    from nl_to_sql.prompts import CLASSIFIER_PROMPT

en vez de:

    from nl_to_sql.prompts.classifier import CLASSIFIER_PROMPT

Ambas formas funcionan; la primera es más corta, la segunda es más
explícita sobre de dónde viene el prompt.
"""

from nl_to_sql.prompts.chat_replies import CHAT_REPLIES
from nl_to_sql.prompts.classifier import CLASSIFIER_PROMPT
from nl_to_sql.prompts.format import FORMAT_PROMPT
from nl_to_sql.prompts.sql_gen import SQL_GEN_PROMPT

__all__ = [
    "CHAT_REPLIES",
    "CLASSIFIER_PROMPT",
    "FORMAT_PROMPT",
    "SQL_GEN_PROMPT",
]
