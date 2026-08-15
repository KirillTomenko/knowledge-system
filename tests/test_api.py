"""Route-level tests. These never call a real LLM (no OPENAI_API_KEY in
CI) — they verify the system's fail-safe behavior instead: no crash, no
invented answers, correct needs_review/audit bookkeeping. Order matters:
the empty-KB test must run before any document is added.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_empty_kb_ask_returns_needs_review():
    """A fresh knowledge base with zero documents must never invent an
    answer — it should short-circuit to needs_review without calling the
    LLM at all."""
    with TestClient(app) as client:
        response = client.post("/kb/ask", json={"question": "что угодно"})
        assert response.status_code == 200
        body = response.json()
        assert body["needs_review"] is True
        assert body["sources"] == []


def test_add_and_list_document():
    with TestClient(app) as client:
        response = client.post(
            "/kb/documents",
            json={
                "title": "Тестовый документ CI",
                "text": "Первый абзац.\n\nВторой абзац с деталями.",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert "document_id" in response.json()

        response = client.get("/kb/documents")
        assert response.status_code == 200
        titles = [d["title"] for d in response.json()]
        assert "Тестовый документ CI" in titles


def test_add_document_rejects_empty_fields():
    with TestClient(app) as client:
        response = client.post("/kb/documents", json={"title": "", "text": ""})
        assert response.status_code == 422  # Pydantic min_length validation


def test_ask_without_llm_key_fails_safe():
    """No OPENAI_API_KEY configured in CI -> the LLM call fails -> the
    endpoint must still return 200 with an honest needs_review answer,
    never a 500."""
    with TestClient(app) as client:
        client.post(
            "/kb/documents",
            json={"title": "Правила", "text": "Рабочий день начинается в 10:00."},
        )
        response = client.post("/kb/ask", json={"question": "Во сколько начинается рабочий день?"})
        assert response.status_code == 200
        body = response.json()
        assert body["needs_review"] is True
        assert body["sources"] == []


def test_audit_and_history_endpoints():
    with TestClient(app) as client:
        client.post("/kb/ask", json={"question": "проверочный вопрос"})
        history = client.get("/kb/history")
        assert history.status_code == 200
        assert len(history.json()) >= 1

        audit = client.get("/kb/audit")
        assert audit.status_code == 200
        actions = {a["action"] for a in audit.json()}
        assert "ask" in actions


def test_web_panel_screens_render():
    with TestClient(app) as client:
        for path in ["/", "/ask", "/history"]:
            response = client.get(path)
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
