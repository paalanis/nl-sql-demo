# BurgerDemo — Bot WhatsApp NL→SQL

Bot de WhatsApp que responde consultas de negocio en lenguaje natural sobre
una cadena de hamburgueserías. Recibe texto o audio, los pasa por un
pipeline de clasificación + generación de SQL + formateo, y devuelve la
respuesta formateada para WhatsApp.

**POC / Demo.** No está pensado para uso en producción sin una revisión
adicional de seguridad, manejo de errores y observabilidad.

---

## Stack

- **FastAPI** — recibe el webhook de WhatsApp Cloud API.
- **RQ (Redis Queue)** — encola cada mensaje para procesamiento asíncrono.
- **Redis** — queue + historial conversacional por usuario (TTL 30 min).
- **MySQL 8** — datos de negocio (ventas, productos, empleados, etc.).
- **Anthropic Claude** — clasificación (Haiku) + generación SQL (Sonnet) + formateo (Sonnet).
- **Groq / Whisper** — transcripción de audios.
- **Railway** — hosting de la API y el worker.
- **Meta for Developers** — proveedor de WhatsApp Cloud API.

---

## Arquitectura del pipeline

Cada mensaje recibido pasa por este flujo:

```
WhatsApp → FastAPI (/webhook) → RQ queue → worker.process_query()
                                                  │
                                                  ▼
                                        run_pipeline(query, history)
                                                  │
                        ┌─────────────────────────┼────────────────────────┐
                        ▼                         ▼                        ▼
              classify_and_rewrite        generate_sql               format_results
                    (Haiku)                 (Sonnet)                    (Sonnet)
                        │                         │                        │
                        │              execute_query (MySQL)               │
                        └───────────── history_entry ─────────────────────┘
                                                  │
                                                  ▼
                                         Redis (history:{user})
                                                  │
                                                  ▼
                                         WhatsApp ← texto formateado
```

**Responsabilidades separadas:**

| Paso | Modelo | Entrada | Salida |
|---|---|---|---|
| `classify_and_rewrite` | Haiku | mensaje + historial estructurado | JSON `{intent, confidence, reasoning, rewritten_query}` |
| `generate_sql` | Sonnet | query autocontenida (ya reescrita si era followup) | SQL para MySQL |
| `format_results` | Sonnet | resultado crudo + query original | texto formateado para WhatsApp |

El clasificador nunca genera SQL. El generador SQL nunca ve historial.
Esta separación elimina de raíz el problema de "contaminación de contexto"
que tenía la arquitectura anterior.

### Los 7 intents

- `GREETING` — "hola", "buenas"
- `HELP` — "qué podés consultar"
- `OUT_OF_SCOPE` — preguntas de negocio no cubiertas por el esquema
- `CHAT_ACK` — "gracias", "ok", "perfecto"
- `CHAT_CORRECTION` — "no era eso", "mejorá el formato"
- `NEW_QUERY` — consulta autocontenida
- `FOLLOWUP_QUERY` — consulta que depende del historial

Cuando el intent es `FOLLOWUP_QUERY`, el clasificador reescribe el mensaje
como una query autocontenida usando el historial, y el generador SQL
recibe esa versión reescrita. Ejemplo: "y las otras?" se convierte en
"Ventas totales de febrero 2026 por cada sucursal excepto Centro".

### Historial estructurado

En vez de guardar el texto con emojis que ve el usuario, Redis almacena
por turno:

```json
{
  "user_message": "cuánto vendió Centro en febrero",
  "intent": "NEW_QUERY",
  "sql": "SELECT SUM(total) FROM ventas WHERE ...",
  "row_count": 1,
  "result_summary": "{'total': 500000.0}"
}
```

Esto le da al clasificador la información mínima que necesita para
resolver referencias ("las otras", "comparalo") sin arrastrar markdown
que confunda al modelo.

---

## Estructura del repo

```
nl-sql-demo/
├── main.py                      # FastAPI + webhook de WhatsApp
├── worker.py                    # RQ worker + orquestación de Redis
├── nl_to_sql/
│   ├── db.py                    # Conexión MySQL
│   ├── pipeline.py              # Pipeline de 3 pasos + orquestación
│   └── prompts/
│       ├── __init__.py          # Reexport para imports cómodos
│       ├── classifier.py        # CLASSIFIER_PROMPT (Haiku)
│       ├── sql_gen.py           # SQL_GEN_PROMPT (Sonnet)
│       ├── format.py            # FORMAT_PROMPT (Sonnet)
│       └── chat_replies.py      # Respuestas canned (sin LLM)
├── scripts/
│   └── validate_env.py          # Smoke test post-deploy
├── seed_burgerdemo.sql          # Dump con datos dummy consistentes
├── Procfile                     # Para Railway
├── requirements.txt
└── .env.example
```

---

## Deploy (Railway)

El stack corre en Railway con 2 servicios que comparten repo y env vars:

- **web**: proceso `web` del `Procfile` → `uvicorn main:app`
- **worker**: proceso `worker` del `Procfile` → `rq worker --url $REDIS_URL`

MySQL y Redis son add-ons gestionados de Railway.

**Webhook de WhatsApp**: en Meta for Developers → WhatsApp → Configuration,
apuntar el webhook a `https://<tu-app>.railway.app/webhook` con el
`WHATSAPP_VERIFY_TOKEN` que pusiste en el env del servicio `web`.

**Validación post-deploy**: correr desde la consola de Railway
(`web` o `worker`):

```bash
python scripts/validate_env.py
```

Debería imprimir ✅ en los 8 checks (env vars, config del pipeline,
conectividad MySQL/Redis, tablas pobladas, invariantes del seed).

---

## Variables de entorno

Ver `.env.example` para la lista completa con comentarios. Resumen:

**Obligatorias:**
- `ANTHROPIC_API_KEY`, `GROQ_API_KEY`
- `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `REDIS_URL`

**Opcionales (con defaults):**
- `CLASSIFIER_MODEL` (default `claude-haiku-4-5`)
- `SQL_MODEL`, `FORMAT_MODEL` (default `claude-sonnet-4-6`)
- `CLASSIFIER_CONFIDENCE_THRESHOLD` (default `0.6`)
- `CLASSIFIER_MAX_TOKENS`, `SQL_MAX_TOKENS`, `FORMAT_MAX_TOKENS`
- `HISTORY_TTL` (default `1800` segundos)
- `MAX_HISTORY_TURNS` (default `5`)

---

## Datos de prueba

El seed (`seed_burgerdemo.sql`) genera ~500 ventas entre Ene–Abr 2026 en
4 sucursales de Buenos Aires. Los totales son consistentes por
construcción: `ventas.total == SUM(detalle_ventas.cantidad * precio_unitario)`
para toda venta.

Generado con `random.seed(42)` — es determinista, podés regenerarlo
cuando quieras y te va a dar exactamente los mismos datos.

---

## Troubleshooting

- **El bot me pide reformular todo**: el `CLASSIFIER_CONFIDENCE_THRESHOLD`
  está muy alto, o el Haiku no está devolviendo JSON válido. Revisá logs
  del servicio `worker`, deberías ver `[PIPELINE] intent=... confidence=...`.
- **Audios no se procesan**: Groq tiene rate limits agresivos en el tier
  gratuito. Revisar logs del worker.
