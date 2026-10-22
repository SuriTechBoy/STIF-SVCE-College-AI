from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.retrieval import answer_question, load_chunks, load_latest_report
from ingestion.run_ingestion import run_ingestion

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="STIF.ai SVCE College Assistant", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(ROOT / "frontend")), name="static")
_ingest_lock = threading.Lock()
_ingest_state: dict[str, Any] = {"status": "idle", "message": "No ingestion job started in this process."}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, str]] = []
    mode: str = "retrieval"


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    chunks = load_chunks()
    return {
        "status": "ok",
        "project": "STIF.ai SVCE College Assistant",
        "college": os.getenv("COLLEGE_NAME", "Sri Venkateswara College of Engineering, Tirupati"),
        "chunks_loaded": len(chunks),
        "llm_configured": bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_MODEL")),
    }


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    result = answer_question(request.message.strip())
    return ChatResponse(**result)


@app.get("/api/v1/ingest/status")
def ingestion_status():
    return {"job": dict(_ingest_state), "last_report": load_latest_report()}


def _run_ingest_task(start_url: str, max_pages: int):
    global _ingest_state
    try:
        _ingest_state.update(status="running", message="Ingestion is running.")
        report = run_ingestion(start_url=start_url, max_pages=max_pages)
        _ingest_state.update(status="completed", message="Ingestion finished.", report=report)
    except Exception as exc:
        _ingest_state.update(status="failed", message=str(exc))


@app.post("/api/v1/ingest/run")
def start_ingestion(background_tasks: BackgroundTasks, max_pages: int | None = None):
    global _ingest_state
    if _ingest_state.get("status") == "running":
        return {"status": "running", "message": "An ingestion job is already running."}
    if not _ingest_lock.acquire(blocking=False):
        return {"status": "running", "message": "An ingestion job is already running."}
    # Run as a background task; release the lock in a wrapper.
    def wrapped():
        try:
            _run_ingest_task(
                os.getenv("START_URL", "https://svce.edu.in/"),
                max_pages or int(os.getenv("MAX_PAGES", "500")),
            )
        finally:
            _ingest_lock.release()
    background_tasks.add_task(wrapped)
    _ingest_state = {"status": "queued", "message": "Ingestion job queued."}
    return {"status": "queued", "message": "Ingestion job queued. Check /api/v1/ingest/status."}
