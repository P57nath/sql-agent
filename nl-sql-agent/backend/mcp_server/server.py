"""
Database access layer.
  - fetch_schema_text() : reads the full schema once at startup
  - run_query(sql)      : executes a validated SELECT and returns JSON
"""
import json
import os
import threading
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool
from dotenv import load_dotenv

from .guardrails import GuardrailError, validate_query

load_dotenv()

DATABASE_URL: str = os.environ["DATABASE_URL"]
MAX_ROWS: int = int(os.getenv("MAX_ROWS", "50"))
QUERY_TIMEOUT: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "10"))
ALLOWED_SCHEMAS: list[str] = os.getenv("ALLOWED_SCHEMAS", "public").split(",")

_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pg_pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    dsn=DATABASE_URL,
                    options="-c default_transaction_read_only=on",
                )
    return _pool


def fetch_schema_text() -> str:
    """
    Read the full database schema and return it as a plain-text string
    ready to be embedded in the LLM system prompt.

    Uses pg_catalog (fast) instead of information_schema.
    Called once at startup; the result is cached by agent.py.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.relname                                        AS table_name,
                    a.attname                                        AS column_name,
                    pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                    NOT a.attnotnull                                 AS is_nullable,
                    col_description(a.attrelid, a.attnum)           AS column_comment
                FROM pg_catalog.pg_attribute a
                JOIN pg_catalog.pg_class c     ON c.oid = a.attrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s)
                  AND c.relkind = 'r'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY c.relname, a.attnum
                """,
                (ALLOWED_SCHEMAS,),
            )
            columns = cur.fetchall()

            cur.execute(
                """
                SELECT
                    c.relname  AS from_table,
                    a.attname  AS from_col,
                    fc.relname AS to_table,
                    fa.attname AS to_col
                FROM pg_catalog.pg_constraint con
                JOIN pg_catalog.pg_class c  ON c.oid  = con.conrelid
                JOIN pg_catalog.pg_class fc ON fc.oid = con.confrelid
                JOIN pg_catalog.pg_namespace n  ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_attribute a  ON a.attrelid  = con.conrelid  AND a.attnum  = con.conkey[1]
                JOIN pg_catalog.pg_attribute fa ON fa.attrelid = con.confrelid AND fa.attnum = con.confkey[1]
                WHERE con.contype = 'f' AND n.nspname = ANY(%s)
                """,
                (ALLOWED_SCHEMAS,),
            )
            fks = cur.fetchall()
        conn.rollback()
    finally:
        pool.putconn(conn)

    # Build FK lookup: "table.col" → "ref_table.ref_col"
    fk_map: dict[str, str] = {
        f"{r['from_table']}.{r['from_col']}": f"{r['to_table']}.{r['to_col']}"
        for r in fks
    }

    # Group columns by table
    tables: dict[str, list[Any]] = {}
    for row in columns:
        tables.setdefault(row["table_name"], []).append(row)

    # Render compact, human-readable schema text
    lines: list[str] = []
    for table_name, cols in tables.items():
        lines.append(f"Table: {table_name}")
        for col in cols:
            parts = [f"  {col['column_name']:<22} {col['data_type']}"]
            if not col["is_nullable"]:
                parts.append("NOT NULL")
            fk = fk_map.get(f"{table_name}.{col['column_name']}")
            if fk:
                parts.append(f"→ {fk}")
            if col["column_comment"]:
                parts.append(f"({col['column_comment']})")
            lines.append(" ".join(parts))
        lines.append("")

    return "\n".join(lines).strip()


def run_query(sql: str) -> str:
    """Validate and execute a SELECT query. Returns a JSON string."""
    try:
        safe_sql = validate_query(sql, max_rows=MAX_ROWS)
    except GuardrailError as exc:
        return json.dumps({"error": str(exc)})

    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{QUERY_TIMEOUT}s'")
            cur.execute(safe_sql)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description] if cur.description else []
        conn.rollback()
        return json.dumps(
            {
                "columns": cols,
                "rows": [dict(r) for r in rows],
                "row_count": len(rows),
                "sql_executed": safe_sql,
            },
            default=str,
        )
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return json.dumps({"error": str(exc)})
    finally:
        pool.putconn(conn)
