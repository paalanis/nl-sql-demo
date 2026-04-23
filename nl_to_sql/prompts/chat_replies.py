"""
Respuestas deterministas para intents no-SQL.

Estas respuestas se devuelven tal cual, sin pasar por ningún LLM.
Ahorran tokens y latencia en los casos más frecuentes: saludos, help,
acks, correcciones.

Cómo editar:
  - Mantener el tono breve y amable.
  - WhatsApp usa *asterisco simple* para negrita (no doble).
  - Emojis OK, moderación: 1 por línea.
  - Mantener menciones consistentes: "BurgerDemo", 4 sucursales
    (Centro, Confluencia, Alta Barda, Cipolletti).

LOW_CONFIDENCE es la respuesta cuando el clasificador no está seguro
(confidence < umbral). No es un intent que devuelva el clasificador —
lo dispara el pipeline cuando decide no confiar en la clasificación.
"""

CHAT_REPLIES = {
    "GREETING": (
        "¡Hola! 👋 Soy el asistente de *BurgerDemo*.\n\n"
        "Puedo consultarte info sobre ventas, productos, stock, empleados y sucursales.\n\n"
        "¿Qué querés saber?"
    ),
    "HELP": (
        "📋 *Esto es lo que puedo consultar:*\n\n"
        "📊 *Ventas* — totales por fecha, sucursal o producto\n"
        "🍔 *Productos* — precios, costos y categorías\n"
        "👥 *Empleados* — roles, turnos y horas trabajadas\n"
        "📦 *Stock* — disponibilidad por sucursal\n"
        "🏪 *Sucursales* — Centro, Confluencia, Alta Barda y Cipolletti\n\n"
        "Escribime en lenguaje natural. 💬"
    ),
    "OUT_OF_SCOPE": (
        "No tengo datos sobre eso en el sistema. 🤔\n\n"
        "Puedo ayudarte con ventas, productos, stock, empleados, sucursales y turnos.\n\n"
        "¿Querés intentar con otra consulta?"
    ),
    "CHAT_ACK": "¡Genial! 👍 ¿Querés consultar algo más?",
    "CHAT_CORRECTION": (
        "Perdón por eso. 🙏 ¿Podés reformular la consulta que tenías en mente? "
        "Así la intento de nuevo."
    ),
    "LOW_CONFIDENCE": (
        "No te entendí bien. 🤔 ¿Podés reformular la consulta? "
        "Podés preguntarme sobre ventas, productos, stock, empleados o sucursales."
    ),
}
