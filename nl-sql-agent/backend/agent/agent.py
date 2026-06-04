"""
Agent orchestration — two backends selectable via AGENT_BACKEND env var:

  AGENT_BACKEND=ollama      (default) — Ollama local model, manual tool loop
  AGENT_BACKEND=anthropic             — Anthropic API with built-in MCP client
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .history import Message, append, get

load_dotenv()

AGENT_BACKEND: str = os.getenv("AGENT_BACKEND", "ollama")

SYSTEM_PROMPT = """You are a friendly, expert data analyst assistant.

You have access to a live business database via two tools:
- get_schema: Always call this FIRST to understand the database structure.
- run_query: Execute a safe SELECT query and get results.

Your workflow for every question:
1. Call get_schema to understand tables and relationships.
2. Write a precise, efficient SQL SELECT query.
3. Call run_query with that SQL.
4. Interpret the results and give a clear, plain-English answer.
5. If relevant, mention the SQL you used (briefly).

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
            "name": "get_schema",
            "description": (
                "Fetch the database schema: table names, column names, data types, "
                "nullability, and foreign key relationships. "
                "Always call this FIRST before writing any SQL."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
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
    from mcp_server.server import _get_schema, _run_query

    args: dict = json.loads(arguments_json) if arguments_json else {}
    if name == "get_schema":
        return _get_schema()
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
        # Append assistant turn (serialise to plain dict for the next request)
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


# def _ask_anthropic(messages: list[dict]) -> dict:
#     """Uses Anthropic's built-in MCP client beta."""
#     import anthropic

#     client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
#     server_dir = str(Path(__file__).parent.parent)

#     resp = client.beta.messages.create(
#         model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
#         max_tokens=2048,
#         system=SYSTEM_PROMPT,
#         messages=messages,
#         mcp_servers=[
#             {
#                 "type": "stdio",
#                 "name": "database",
#                 "command": sys.executable,
#                 "args": ["-m", "mcp_server.server"],
#                 "cwd": server_dir,
#                 "env": {k: v for k, v in os.environ.items() if v is not None},
#             }
#         ],
#         betas=["mcp-client-2025-04-04"],
#     )

#     answer = ""
#     sql_used = None
#     row_count = None

#     for block in resp.content:
#         if hasattr(block, "text"):
#             answer = block.text
#         if hasattr(block, "type") and block.type == "tool_result":
#             try:
#                 raw = block.content[0].text if block.content else ""
#                 data = json.loads(raw)
#                 if "sql_executed" in data:
#                     sql_used = data["sql_executed"]
#                 if "row_count" in data:
#                     row_count = data["row_count"]
#             except Exception:
#                 pass

#     return {"answer": answer, "sql_used": sql_used, "row_count": row_count}


def ask(question: str, session_id: str = "default") -> dict:
    """
    Send a question to the configured LLM backend.
    Returns: answer, sql_used, row_count, session_id.
    """
    history: list[Message] = get(session_id)
    append(session_id, "user", question)
    messages: list[dict] = [*history, {"role": "user", "content": question}]

    if AGENT_BACKEND == "anthropic":
        result = _ask_anthropic(messages)
    else:
        result = _ask_ollama(messages)

    append(session_id, "assistant", result["answer"])
    return {**result, "session_id": session_id}
