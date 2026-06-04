"""
Agent — schema is fetched once at startup and embedded in the system prompt.
Works with any PostgreSQL database; no hardcoded table names anywhere.
"""
import json
import os
import threading

from dotenv import load_dotenv

from .history import Message, append, get

load_dotenv()

# ── System prompt template ────────────────────────────────────────────────────
# {schema} is replaced once at startup with the actual database schema.
_PROMPT_TEMPLATE = """\
You are a friendly, expert data analyst assistant.

You are connected to a PostgreSQL database with the following schema:

{schema}

You have one tool:
- run_query: Execute a SELECT query and return the results.

Your workflow for every question:
1. Study the schema above to identify the relevant tables and columns.
2. Write a precise SELECT query. Always include a LIMIT clause.
3. Call run_query with that SQL.
4. Interpret the results and give a clear, plain-English answer.
5. Briefly mention the SQL you used if it helps the user understand.

Rules:
- Only write SELECT statements. Never INSERT, UPDATE, DELETE, or DROP.
- If a question cannot be answered from the available data, say so clearly.
- Format numbers nicely (e.g. $2,400 not 2400.0).
- Keep answers concise — one to three paragraphs maximum.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_query",
            "description": "Execute a read-only SELECT query against the database and return the results as JSON.",
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
    }
]

# ── Schema cache — built once, reused for every request ──────────────────────
_system_prompt: str | None = None
_prompt_lock = threading.Lock()


def _get_system_prompt() -> str:
    global _system_prompt
    if _system_prompt is None:
        with _prompt_lock:
            if _system_prompt is None:
                from mcp_server.server import fetch_schema_text
                _system_prompt = _PROMPT_TEMPLATE.format(
                    schema=fetch_schema_text()
                )
    return _system_prompt


def warmup() -> None:
    """Fetch and cache the schema. Called once at startup before serving traffic."""
    _get_system_prompt()


# ── Ollama client — created once ─────────────────────────────────────────────
_ollama_client = None
_client_lock = threading.Lock()


def _get_ollama_client():
    global _ollama_client
    if _ollama_client is None:
        with _client_lock:
            if _ollama_client is None:
                from openai import OpenAI
                _ollama_client = OpenAI(
                    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                    api_key="ollama",
                )
    return _ollama_client


# ── Tool execution ────────────────────────────────────────────────────────────
def _execute_tool(name: str, arguments_json: str) -> str:
    from mcp_server.server import run_query
    args: dict = json.loads(arguments_json) if arguments_json else {}
    if name == "run_query":
        return run_query(args.get("sql", ""))
    return json.dumps({"error": f"Unknown tool: {name}"})


# ── LLM loop ──────────────────────────────────────────────────────────────────
def _ask_ollama(messages: list[dict]) -> dict:
    client = _get_ollama_client()
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    chat: list[dict] = [{"role": "system", "content": _get_system_prompt()}, *messages]
    sql_used: str | None = None
    row_count: int | None = None

    for _ in range(10):
        resp = client.chat.completions.create(
            model=model,
            messages=chat,
            tools=_TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        chat.append(msg.model_dump(exclude_unset=True, exclude_none=True))

        if not msg.tool_calls:
            return {"answer": msg.content or "", "sql_used": sql_used, "row_count": row_count}

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
            chat.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return {"answer": "Maximum iterations reached.", "sql_used": sql_used, "row_count": row_count}


# ── Public API ────────────────────────────────────────────────────────────────
def ask(question: str, session_id: str = "default") -> dict:
    history: list[Message] = get(session_id)
    append(session_id, "user", question)
    messages: list[dict] = [*history, {"role": "user", "content": question}]
    result = _ask_ollama(messages)
    append(session_id, "assistant", result["answer"])
    return {**result, "session_id": session_id}
