"""FastAPI entry point for the NL → SQL agent."""
import asyncio
import os
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent as agent_module
from . import history

load_dotenv()

app = FastAPI(title="NL → SQL Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    """Fetch the database schema once so the first user request is fast."""
    await asyncio.to_thread(agent_module.warmup)


class AskRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    sql_used: Optional[str] = None
    row_count: Optional[int] = None
    session_id: str


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    session_id = req.session_id or str(uuid.uuid4())
    try:
        result = await asyncio.to_thread(agent_module.ask, req.question, session_id)
        return AskResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/session/{session_id}")
async def clear_session(session_id: str) -> dict:
    history.clear(session_id)
    return {"cleared": session_id}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
