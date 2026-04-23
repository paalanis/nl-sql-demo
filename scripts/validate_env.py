"""
Script de validación de entorno para BurgerDemo.

Verifica en orden:
  1) Conectividad con MySQL y Redis.
  2) Las tablas esperadas existen y no están vacías.
  3) Los 3 invariantes de integridad del seed:
     - ventas.total == SUM(detalle_ventas.cantidad * precio_unitario)
     - Toda venta tiene al menos 1 detalle asociado.
     - No hay detalle huérfano (apuntando a ventas o productos inexistentes).
  4) Las env vars obligatorias están presentes.
  5) Modelos y umbrales del pipeline tienen valores válidos.

Uso:
  python scripts/validate_env.py

Exit code 0 si todo OK, 1 si hay alguna falla.
Útil como smoke test post-deploy en Railway, o como precheck antes
de demos.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---- Codifiquemos los checks como funciones que devuelven (ok: bool, msg: str)

REQUIRED_ENV = [
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "WHATSAPP_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_VERIFY_TOKEN",
    "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME",
    "REDIS_URL",
]

EXPECTED_TABLES = [
    "sucursales", "productos", "empleados",
    "ventas", "detalle_ventas", "stock", "turnos",
]


def check_env_vars():
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        return False, f"Faltan env vars: {', '.join(missing)}"
    return True, f"{len(REQUIRED_ENV)} env vars presentes"


def check_pipeline_config():
    from nl_to_sql import pipeline
    issues = []
    if not (0.0 <= pipeline.CONFIDENCE_THRESHOLD <= 1.0):
        issues.append(f"CONFIDENCE_THRESHOLD fuera de rango: {pipeline.CONFIDENCE_THRESHOLD}")
    for name, val in [
        ("CLASSIFIER_MAX_TOKENS", pipeline.CLASSIFIER_MAX_TOKENS),
        ("SQL_MAX_TOKENS", pipeline.SQL_MAX_TOKENS),
        ("FORMAT_MAX_TOKENS", pipeline.FORMAT_MAX_TOKENS),
    ]:
        if val <= 0:
            issues.append(f"{name} no positivo: {val}")
    if issues:
        return False, "; ".join(issues)
    return True, (
        f"classifier={pipeline.CLASSIFIER_MODEL}/{pipeline.CLASSIFIER_MAX_TOKENS}t, "
        f"sql={pipeline.SQL_MODEL}/{pipeline.SQL_MAX_TOKENS}t, "
        f"format={pipeline.FORMAT_MODEL}/{pipeline.FORMAT_MAX_TOKENS}t, "
        f"threshold={pipeline.CONFIDENCE_THRESHOLD}"
    )


def check_mysql_connectivity():
    try:
        from nl_to_sql.db import get_connection
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        conn.close()
        return True, "conexión OK"
    except Exception as e:
        return False, f"{e.__class__.__name__}: {e}"


def check_tables_exist():
    from nl_to_sql.db import execute_query
    missing = []
    stats = {}
    for t in EXPECTED_TABLES:
        try:
            rows = execute_query(f"SELECT COUNT(*) AS n FROM {t}")
            n = rows[0]["n"]
            stats[t] = n
            if n == 0:
                missing.append(f"{t} (vacía)")
        except Exception as e:
            missing.append(f"{t} ({e.__class__.__name__})")
    if missing:
        return False, f"Tablas con problemas: {', '.join(missing)}"
    stats_str = ", ".join(f"{t}={n}" for t, n in stats.items())
    return True, stats_str


def check_invariant_total_equals_detail():
    from nl_to_sql.db import execute_query
    rows = execute_query("""
        SELECT v.id, v.total, SUM(d.cantidad * d.precio_unitario) AS suma_detalle
        FROM ventas v
        JOIN detalle_ventas d ON d.id_venta = v.id
        GROUP BY v.id, v.total
        HAVING ABS(v.total - SUM(d.cantidad * d.precio_unitario)) > 0.01
    """)
    if rows:
        sample = rows[0]
        return False, (
            f"{len(rows)} ventas con mismatch "
            f"(ej: venta {sample['id']}: total={sample['total']} vs detalle={sample['suma_detalle']})"
        )
    return True, "ventas.total coincide con SUM(detalle) en todas las ventas"


def check_invariant_every_sale_has_detail():
    from nl_to_sql.db import execute_query
    rows = execute_query("""
        SELECT v.id
        FROM ventas v
        LEFT JOIN detalle_ventas d ON d.id_venta = v.id
        WHERE d.id IS NULL
        LIMIT 5
    """)
    if rows:
        ids = ", ".join(str(r["id"]) for r in rows)
        return False, f"Ventas sin detalle asociado: {ids}..."
    return True, "toda venta tiene al menos 1 detalle"


def check_invariant_no_orphan_details():
    from nl_to_sql.db import execute_query
    rows = execute_query("""
        SELECT d.id
        FROM detalle_ventas d
        LEFT JOIN ventas v    ON v.id = d.id_venta
        LEFT JOIN productos p ON p.id = d.id_producto
        WHERE v.id IS NULL OR p.id IS NULL
        LIMIT 5
    """)
    if rows:
        ids = ", ".join(str(r["id"]) for r in rows)
        return False, f"Detalle huérfano: ids {ids}..."
    return True, "detalle_ventas sin huérfanos"


def check_redis_connectivity():
    try:
        import redis
        r = redis.from_url(os.environ["REDIS_URL"])
        r.ping()
        key_count = r.dbsize()
        return True, f"conexión OK ({key_count} keys)"
    except Exception as e:
        return False, f"{e.__class__.__name__}: {e}"


# ---- Runner ----------------------------------------------------------------

CHECKS = [
    ("Env vars obligatorias", check_env_vars),
    ("Config del pipeline", check_pipeline_config),
    ("Conectividad MySQL", check_mysql_connectivity),
    ("Tablas y conteos", check_tables_exist),
    ("Invariante 1: total == SUM(detalle)", check_invariant_total_equals_detail),
    ("Invariante 2: toda venta tiene detalle", check_invariant_every_sale_has_detail),
    ("Invariante 3: sin detalle huérfano", check_invariant_no_orphan_details),
    ("Conectividad Redis", check_redis_connectivity),
]


def main():
    print("=" * 68)
    print(" BurgerDemo — Validación de entorno")
    print("=" * 68)

    all_ok = True
    for name, fn in CHECKS:
        try:
            ok, msg = fn()
        except Exception as e:
            ok, msg = False, f"EXCEPCIÓN: {e.__class__.__name__}: {e}"
        icon = "✅" if ok else "❌"
        print(f"{icon} {name}")
        print(f"   {msg}")
        if not ok:
            all_ok = False

    print("=" * 68)
    if all_ok:
        print(" Todo OK ✨")
        return 0
    print(" Hay checks fallando ⚠️")
    return 1


if __name__ == "__main__":
    sys.exit(main())
