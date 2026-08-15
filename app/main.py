import json
import os
import re
import time
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import database as db
from app import llm
from app.search import HybridSearch

_search = HybridSearch()
AUTO_SEED_DEMO_DATA = os.getenv("AUTO_SEED_DEMO_DATA", "true").lower() in ("1", "true", "yes")


def _reindex_all():
    _search.reindex(db.all_snippets())


def _split_into_snippets(text: str):
    """Simple paragraph split, as explicitly allowed by the spec."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return parts or [text.strip()]


def _seed_demo_data_if_empty():
    """Auto-loads the 5 test documents on startup when the knowledge base
    is empty. Matters most on free hosting tiers (e.g. Render) where the
    container — and its filesystem, including the SQLite file — resets on
    every sleep/wake cycle: without this, a demo link can silently point
    at an empty knowledge base after 15 minutes of inactivity."""
    if not AUTO_SEED_DEMO_DATA:
        return
    if db.list_documents():
        return  # already has data — never overwrite real content

    seed_path = os.path.join(BASE_DIR, "tests_data", "kb_documents.jsonl")
    if not os.path.exists(seed_path):
        return

    with open(seed_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            doc_id = db.insert_document(doc["title"], doc["text"])
            for chunk in _split_into_snippets(doc["text"]):
                db.insert_snippet(doc_id, chunk)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    _seed_demo_data_if_empty()
    _reindex_all()
    yield


app = FastAPI(title="Team Knowledge System", lifespan=lifespan)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def _audit(action: str, input_data: dict, fn):
    """Runs fn(), logs the call to audit_runs regardless of outcome,
    and re-raises so FastAPI still returns the right HTTP error."""
    start = time.perf_counter()
    status = "ok"
    error = None
    output_data = None
    try:
        output_data = fn()
        return output_data
    except Exception as exc:
        status = "error"
        error = str(exc)
        raise
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        db.insert_audit_run(
            action=action,
            input_data=json.dumps(input_data, ensure_ascii=False)[:4000],
            output_data=json.dumps(output_data, ensure_ascii=False)[:4000] if output_data else None,
            status=status,
            error=error,
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------
# 1) Добавить документ
# ---------------------------------------------------------------------
class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)


@app.post("/kb/documents")
def add_document(payload: DocumentIn):
    def _run():
        doc_id = db.insert_document(payload.title, payload.text)
        for chunk in _split_into_snippets(payload.text):
            db.insert_snippet(doc_id, chunk)
        _reindex_all()
        return {"status": "ok", "document_id": doc_id}

    try:
        return _audit("add_document", payload.model_dump(), _run)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------
# 2) Витрина документов
# ---------------------------------------------------------------------
@app.get("/kb/documents")
def get_documents():
    return _audit("list_documents", {}, db.list_documents)


# ---------------------------------------------------------------------
# 3) Вопрос к базе знаний (строгий JSON, с источниками или needs_review)
# ---------------------------------------------------------------------
class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.post("/kb/ask")
def ask(payload: AskIn):
    def _run():
        snippets = _search.search(payload.question)
        try:
            result = llm.answer_with_sources(payload.question, snippets)
            error = None
        except Exception as exc:
            # infra/LLM failure: fail safe into needs_review, never invent
            result = {
                "answer": "Данных недостаточно: не удалось получить ответ от модели.",
                "confidence": 0.0,
                "sources": [],
                "needs_review": True,
                "review_reason": "llm_error",
            }
            error = str(exc)

        db.insert_qa_run(
            question=payload.question,
            answer=result["answer"],
            sources_json=json.dumps(result["sources"], ensure_ascii=False),
            needs_review=result["needs_review"],
            error=error or result.get("review_reason"),
        )
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "needs_review": result["needs_review"],
        }

    return _audit("ask", payload.model_dump(), _run)


# ---------------------------------------------------------------------
# История (для веб-панели)
# ---------------------------------------------------------------------
@app.get("/kb/history")
def get_history(needs_review_only: bool = False, limit: int = 100):
    return db.list_qa_runs(limit=limit, needs_review_only=needs_review_only)


@app.get("/kb/audit")
def get_audit(limit: int = 100):
    return db.list_audit_runs(limit=limit)


# ---------------------------------------------------------------------
# Веб-панель (3 экрана)
# ---------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def screen_documents(request: Request):
    return templates.TemplateResponse(
        request, "documents.html", {"documents": db.list_documents()}
    )


@app.get("/ask", response_class=HTMLResponse)
def screen_ask(request: Request):
    return templates.TemplateResponse(request, "ask.html", {})


@app.get("/history", response_class=HTMLResponse)
def screen_history(request: Request):
    return templates.TemplateResponse(
        request,
        "history.html",
        {"runs": db.list_qa_runs(limit=100), "audit": db.list_audit_runs(limit=50)},
    )
