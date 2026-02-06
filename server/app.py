from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[1]
IFC_DIR = REPO_ROOT / "IFC-Files"
WEB_DIST = REPO_ROOT / "web" / "dist"
OUTPUT_DIR = REPO_ROOT / "output"

PARSER_DIR = REPO_ROOT / "parser"
sys.path.insert(0, str(PARSER_DIR))

from command_r_agent import CommandRAgent
from ifc_graph_tool import query_ifc_graph
from . import csv_to_graph


app = FastAPI(title="rag-tag IFC Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if IFC_DIR.is_dir():
    app.mount("/ifc", StaticFiles(directory=IFC_DIR), name="ifc")

if OUTPUT_DIR.is_dir():
    app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: str | None = None
    ifc_file: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    tool_history: list[dict[str, Any]]


_GRAPH_LOCK = threading.Lock()
_GRAPH_CACHE: dict[str, Any] = {}
_AGENT_LOCK = threading.Lock()
_AGENT: CommandRAgent | None = None
_SESSIONS: dict[str, dict[str, Any]] = {}


def _get_agent() -> CommandRAgent:
    global _AGENT
    if _AGENT is not None:
        return _AGENT
    with _AGENT_LOCK:
        if _AGENT is None:
            _AGENT = CommandRAgent()
    return _AGENT


def _resolve_ifc_file(ifc_name: str | None) -> Path:
    if ifc_name:
        candidate = (IFC_DIR / ifc_name).resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"IFC file not found: {ifc_name}")
        return candidate
    return csv_to_graph.resolve_ifc_file()


def _get_graph(ifc_name: str | None) -> Any:
    resolved = _resolve_ifc_file(ifc_name)
    key = str(resolved)
    if key in _GRAPH_CACHE:
        return _GRAPH_CACHE[key]
    with _GRAPH_LOCK:
        if key in _GRAPH_CACHE:
            return _GRAPH_CACHE[key]
        graph = csv_to_graph.load_graph(key)
        _GRAPH_CACHE[key] = graph
        return graph


def _get_session(session_id: str | None) -> tuple[str, dict[str, Any]]:
    sid = session_id or uuid.uuid4().hex
    state = _SESSIONS.setdefault(sid, {"history": []})
    return sid, state


@app.get("/api/ifc")
def list_ifc_files() -> dict[str, list[str]]:
    if not IFC_DIR.is_dir():
        raise HTTPException(status_code=404, detail="IFC-Files directory not found.")
    files = sorted(p.name for p in IFC_DIR.iterdir() if p.suffix.lower() == ".ifc")
    return {"files": files}


@app.get("/api/ifc/default")
def default_ifc_file() -> dict[str, str]:
    try:
        default_file = csv_to_graph.resolve_ifc_file()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"file": default_file.name}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question is required.")

    try:
        G = _get_graph(req.ifc_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session_id, state = _get_session(req.session_id)
    try:
        agent = _get_agent()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    max_steps = 6
    result_answer = ""
    for _ in range(max_steps):
        step = agent.plan(req.question, state)
        step_type = step.get("type")
        if step_type == "final":
            result_answer = step.get("answer", "")
            break
        if step_type != "tool":
            result_answer = "Agent returned an invalid step type."
            break
        action = step.get("action")
        params = step.get("params", {})
        tool_result = query_ifc_graph(G, action, params)
        state["history"].append(
            {"tool": {"action": action, "params": params}, "result": tool_result}
        )
    else:
        result_answer = "Max steps exceeded."

    return ChatResponse(
        session_id=session_id,
        answer=result_answer,
        tool_history=state["history"],
    )


@app.get("/api/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/graph")
def graph_html() -> FileResponse:
    graph_file = OUTPUT_DIR / "ifc_graph.html"
    if not graph_file.is_file():
        raise HTTPException(
            status_code=404,
            detail="ifc_graph.html not found. Run parser/csv_to_graph.py first.",
        )
    return FileResponse(graph_file)


@app.get("/")
def index() -> FileResponse:
    if not WEB_DIST.is_dir():
        raise HTTPException(
            status_code=404,
            detail="web/dist not found. Run the frontend build first.",
        )
    return FileResponse(WEB_DIST / "index.html")
