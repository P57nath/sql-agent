"""
MCP server exposing three tools:
  - list_tables  → compact table catalogue (names, column count, links)
  - get_schema   → full column detail for specific tables only
  - run_query    → executes a validated SELECT and returns rows as JSON
"""
import json
import os
import threading
import time
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .guardrails import GuardrailError, validate_query

load_dotenv()

DATABASE_URL: str = os.environ["DATABASE_URL"]
MAX_ROWS: int = int(os.getenv("MAX_ROWS", "50"))
QUERY_TIMEOUT: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "10"))
ALLOWED_SCHEMAS: list[str] = os.getenv("ALLOWED_SCHEMAS", "public").split(",")
_TABLES_TTL: int = int(os.getenv("SCHEMA_CACHE_TTL_SECONDS", "300"))

# Connection pool — reuses TCP connections instead of opening a new one each call
_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()

# Table catalogue cache (list_tables result) — cached for _TABLES_TTL seconds
_tables_cache: str | None = None
_tables_cache_time: float = 0.0


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


app = Server("nl-sql-agent")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_tables",
            description=(
                "Returns a compact catalogue of every table: name, column count, "
                "table comment, and which other tables it links to via foreign keys. "
                "Always call this FIRST to identify which tables are relevant to the question."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_schema",
            description=(
                "Fetch full column details (names, types, nullability, comments, FK relationships) "
                "for a specific list of tables. Call list_tables first, then call this with only "
                "the tables you actually need — do not fetch all tables."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tables": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Table names to fetch schema for.",
                    }
                },
                "required": ["tables"],
            },
        ),
        Tool(
            name="run_query",
            description=(
                "Execute a read-only SELECT query against the database. "
                f"Returns columns and up to {MAX_ROWS} rows as JSON. "
                "Only SELECT statements are allowed — no writes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A valid SELECT SQL statement.",
                    }
                },
                "required": ["sql"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "list_tables":
        return [TextContent(type="text", text=_list_tables())]
    if name == "get_schema":
        return [TextContent(type="text", text=_get_schema(arguments.get("tables", [])))]
    if name == "run_query":
        return [TextContent(type="text", text=_run_query(arguments["sql"]))]
    raise ValueError(f"Unknown tool: {name}")


def _list_tables() -> str:
    """Return a compact table catalogue. Cached for _TABLES_TTL seconds."""
    global _tables_cache, _tables_cache_time
    now = time.monotonic()
    if _tables_cache is not None and (now - _tables_cache_time) < _TABLES_TTL:
        return _tables_cache

    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.relname              AS table_name,
                    obj_description(c.oid) AS table_comment,
                    COUNT(a.attnum)        AS column_count
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_catalog.pg_attribute a
                    ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                WHERE n.nspname = ANY(%s) AND c.relkind = 'r'
                GROUP BY c.relname, c.oid
                ORDER BY c.relname
                """,
                (ALLOWED_SCHEMAS,),
            )
            tables = cur.fetchall()

            cur.execute(
                """
                SELECT
                    c.relname  AS from_table,
                    fc.relname AS to_table
                FROM pg_catalog.pg_constraint con
                JOIN pg_catalog.pg_class c  ON c.oid  = con.conrelid
                JOIN pg_catalog.pg_class fc ON fc.oid = con.confrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE con.contype = 'f' AND n.nspname = ANY(%s)
                """,
                (ALLOWED_SCHEMAS,),
            )
            fks = cur.fetchall()
        conn.rollback()
    finally:
        pool.putconn(conn)

    links: dict[str, list[str]] = {}
    for fk in fks:
        links.setdefault(fk["from_table"], []).append(fk["to_table"])

    catalogue: dict[str, Any] = {
        t["table_name"]: {
            "columns": t["column_count"],
            "comment": t["table_comment"],
            "links_to": links.get(t["table_name"], []),
        }
        for t in tables
    }

    result = json.dumps(catalogue, default=str)
    _tables_cache = result
    _tables_cache_time = now
    return result


def _get_schema(tables: list[str]) -> str:
    """Return full column detail for the requested tables using pg_catalog (fast)."""
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
                  AND c.relname = ANY(%s)
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY c.relname, a.attnum
                """,
                (ALLOWED_SCHEMAS, tables),
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
                JOIN pg_catalog.pg_namespace n  ON n.oid  = c.relnamespace
                JOIN pg_catalog.pg_attribute a  ON a.attrelid  = con.conrelid  AND a.attnum  = con.conkey[1]
                JOIN pg_catalog.pg_attribute fa ON fa.attrelid = con.confrelid AND fa.attnum = con.confkey[1]
                WHERE con.contype = 'f'
                  AND n.nspname = ANY(%s)
                  AND c.relname = ANY(%s)
                """,
                (ALLOWED_SCHEMAS, tables),
            )
            fks = cur.fetchall()
        conn.rollback()
    finally:
        pool.putconn(conn)

    schema: dict[str, Any] = {}
    for row in columns:
        tbl = row["table_name"]
        schema.setdefault(tbl, {"columns": [], "foreign_keys": []})
        schema[tbl]["columns"].append(
            {
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"],
                "comment": row["column_comment"],
            }
        )
    for fk in fks:
        tbl = fk["from_table"]
        if tbl in schema:
            schema[tbl]["foreign_keys"].append(
                f"{fk['from_col']} → {fk['to_table']}.{fk['to_col']}"
            )

    return json.dumps(schema, default=str)


def _run_query(sql: str) -> str:
    """Validate then execute a SELECT query. Returns JSON."""
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


if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(app))
