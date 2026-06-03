"""
MCP server exposing two tools to Claude:
  - get_schema   → returns table/column metadata
  - run_query    → executes a validated SELECT and returns rows as JSON
"""
import json
import os
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .guardrails import GuardrailError, validate_query

load_dotenv()

DATABASE_URL: str = os.environ["DATABASE_URL"]
MAX_ROWS: int = int(os.getenv("MAX_ROWS", "500"))
QUERY_TIMEOUT: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "10"))
ALLOWED_SCHEMAS: list[str] = os.getenv("ALLOWED_SCHEMAS", "public").split(",")


def _get_connection() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(DATABASE_URL)
    conn.set_session(readonly=True, autocommit=False)
    return conn


app = Server("nl-sql-agent")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_schema",
            description=(
                "Fetch the database schema: table names, column names, data types, "
                "nullability, and foreign key relationships. "
                "Always call this FIRST before writing any SQL."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="run_query",
            description=(
                "Execute a read-only SELECT query against the database. "
                "Returns columns and up to MAX_ROWS rows as JSON. "
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
    if name == "get_schema":
        return [TextContent(type="text", text=_get_schema())]
    if name == "run_query":
        return [TextContent(type="text", text=_run_query(arguments["sql"]))]
    raise ValueError(f"Unknown tool: {name}")


def _get_schema() -> str:
    """Return rich schema metadata as JSON."""
    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    c.table_schema,
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    col_description(
                        (c.table_schema||'.'||c.table_name)::regclass,
                        c.ordinal_position
                    ) AS column_comment
                FROM information_schema.columns c
                WHERE c.table_schema = ANY(%s)
                ORDER BY c.table_schema, c.table_name, c.ordinal_position
                """,
                (ALLOWED_SCHEMAS,),
            )
            columns = cur.fetchall()

            cur.execute(
                """
                SELECT
                    tc.table_name  AS from_table,
                    kcu.column_name AS from_col,
                    ccu.table_name  AS to_table,
                    ccu.column_name AS to_col
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                """
            )
            fks = cur.fetchall()

        schema: dict[str, Any] = {}
        for row in columns:
            tbl = row["table_name"]
            schema.setdefault(tbl, {"columns": [], "foreign_keys": []})
            schema[tbl]["columns"].append(
                {
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"] == "YES",
                    "comment": row["column_comment"],
                }
            )
        for fk in fks:
            tbl = fk["from_table"]
            if tbl in schema:
                schema[tbl]["foreign_keys"].append(
                    f"{fk['from_col']} → {fk['to_table']}.{fk['to_col']}"
                )

        return json.dumps(schema, indent=2, default=str)
    finally:
        conn.close()


def _run_query(sql: str) -> str:
    """Validate then execute a SELECT query. Returns JSON."""
    try:
        safe_sql = validate_query(sql, max_rows=MAX_ROWS)
    except GuardrailError as exc:
        return json.dumps({"error": str(exc)})

    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SET statement_timeout = '{QUERY_TIMEOUT}s'")
            cur.execute(safe_sql)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description] if cur.description else []
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
        return json.dumps({"error": str(exc)})
    finally:
        conn.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(app))
