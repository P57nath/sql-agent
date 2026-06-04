"""
Agent orchestration — two backends selectable via AGENT_BACKEND env var:

  AGENT_BACKEND=ollama      (default) — Ollama local model, manual tool loop
  AGENT_BACKEND=anthropic             — Anthropic API with built-in MCP client
"""
import json
import os

from dotenv import load_dotenv

from .history import Message, append, get

load_dotenv()

AGENT_BACKEND: str = os.getenv("AGENT_BACKEND", "ollama")

SYSTEM_PROMPT = """You are a friendly, expert data analyst assistant.

You have access to a live business database via three tools:
- list_tables : Always call this FIRST. Returns every table name, its column count, and which tables it links to.
- get_schema  : Call this with only the tables relevant to the question. Returns full column details and FK relationships.
- run_query   : Execute a safe SELECT query and get results.

Your workflow for every question:
1. Call list_tables to discover available tables.
2. Identify which tables are needed, then call get_schema with only those table names.
3. Write a precise, efficient SQL SELECT query based on the schema.
4. Call run_query with that SQL.
5. Interpret the results and give a clear, plain-English answer.
6. If relevant, mention the SQL you used (briefly).

Rules:
- Only write SELECT statements. Never INSERT, UPDATE, DELETE, or DROP.
- Always add a LIMIT if not already present.
- If a question cannot be answered from the database, say so clearly.
- Format numbers nicely (e.g. $2,400 not 2400.0).
- Keep answers concise — one to three paragraphs maximum.
"""

# Tool definitions in OpenAI function-calling format (used by Ollama backend)
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_tables",
            "description": (
                "Returns a compact catalogue of every table: name, column count, "
                "table comment, and which other tables it links to via foreign keys. "
                "Always call this FIRST to identify which tables are relevant to the question."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": (
                "Fetch full column details (names, types, nullability, comments, FK relationships) "
                "for a specific list of tables. Call list_tables first, then call this with only "
                "the tables you actually need — do not fetch all tables."
            ),
            "parameters": {
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
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_query",
            "description": (
                "Execute a read-only SELECT query against the database. "
                "Returns columns and rows as JSON. Only SELECT statements are allowed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A valid SELECT SQL statement.",
                    }
                },
                "required": ["sql"],
            },
        },
    },
]


def _execute_tool(name: str, arguments_json: str) -> str:
    """Call mcp_server Python functions directly — no subprocess needed."""
    from mcp_server.server import _get_schema, _list_tables, _run_query

    args: dict = json.loads(arguments_json) if arguments_json else {}
    if name == "list_tables":
        return _list_tables()
    if name == "get_schema":
        return _get_schema(args.get("tables", []))
    if name == "run_query":
        return _run_query(args.get("sql", ""))
    return json.dumps({"error": f"Unknown tool: {name}"})


_ollama_client: "OpenAI | None" = None  # type: ignore[name-defined]


def _get_ollama_client() -> "OpenAI":  # type: ignore[name-defined]
    global _ollama_client
    if _ollama_client is None:
        from openai import OpenAI
        _ollama_client = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key="ollama",
        )
    return _ollama_client


def _ask_ollama(messages: list[dict]) -> dict:
    """Agentic loop against Ollama's OpenAI-compatible endpoint."""
    client = _get_ollama_client()
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    chat: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    sql_used: str | None = None
    row_count: int | None = None

    for _ in range(10):  # hard cap to prevent runaway loops
        resp = client.chat.completions.create(
            model=model,
            messages=chat,
            tools=_TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        chat.append(msg.model_dump(exclude_unset=True, exclude_none=True))

        if not msg.tool_calls:
            return {
                "answer": msg.content or "",
                "sql_used": sql_used,
                "row_count": row_count,
            }

        for tc in msg.tool_calls:
            result = _execute_tool(tc.function.name, tc.function.arguments)
            try:
                data = json.loads(result)
                if "sql_executed" in data:
                    sql_used = data["sql_executed"]
                if "row_count" in data:
                    row_count = data["row_count"]
            except Exception:
                pass
            chat.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

    return {
        "answer": "Maximum tool iterations reached without a final answer.",
        "sql_used": sql_used,
        "row_count": row_count,
    }


def ask(question: str, session_id: str = "default") -> dict:
    """
    Send a question to the configured LLM backend.
    Returns: answer, sql_used, row_count, session_id.
    """
    history: list[Message] = get(session_id)
    append(session_id, "user", question)
    messages: list[dict] = [*history, {"role": "user", "content": question}]

    result = _ask_ollama(messages)

    append(session_id, "assistant", result["answer"])
    return {**result, "session_id": session_id}
