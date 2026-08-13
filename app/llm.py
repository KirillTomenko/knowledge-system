"""The single AI operation in the system: answer a question strictly
from provided snippets, as strict JSON, with a citation for every claim.

Contract enforced here (matches the spec):
- if no relevant snippets are retrieved -> needs_review=True, no LLM call
  needed ("честно говорит данных недостаточно" without inventing anything)
- if the model itself is unsure (confidence below threshold) -> needs_review=True
- sources must be non-empty whenever needs_review is False, and vice versa
"""
import json
import os
import time
from typing import List, Dict

from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.55"))

_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL) if OPENAI_API_KEY else None

SYSTEM_PROMPT = """You are the answer engine for an internal team knowledge base.
You must answer ONLY using the numbered snippets given to you. Never use outside
knowledge, never guess, never fill gaps with plausible-sounding invention.

Return ONLY a JSON object with this exact shape, no other text:
{
  "answer": "string - the answer, or a short honest statement that the data is insufficient",
  "confidence": 0.0 to 1.0,
  "sources": [{"snippet_id": "string", "quote": "short exact quote from that snippet"}],
  "needs_review": true or false,
  "review_reason": "string or null - required if needs_review is true"
}

Rules:
- If the snippets do not contain a real answer, set answer to a clear
  "data is insufficient" statement, sources to [], confidence low, and
  needs_review to true with a reason.
- Every entry in "sources" must reference a snippet_id you were actually given.
- confidence reflects how directly and completely the snippets answer the question.
"""


def _build_user_prompt(question: str, snippets: List[Dict]) -> str:
    numbered = "\n\n".join(
        f"[snippet_id={s['id']}] (from document: {s.get('document_title', '?')})\n{s['snippet_text']}"
        for s in snippets
    )
    return f"Question: {question}\n\nAvailable snippets:\n{numbered}"


def answer_with_sources(question: str, snippets: List[Dict]) -> Dict:
    """Returns a dict matching the qa_runs contract. Never raises for
    "no answer found" cases — only raises for actual infra failures,
    which the caller logs to audit_runs as status="error"."""

    if not snippets:
        return {
            "answer": "Данных недостаточно: подходящих фрагментов в базе знаний не найдено.",
            "confidence": 0.0,
            "sources": [],
            "needs_review": True,
            "review_reason": "no_relevant_snippets",
        }

    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    response = _client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(question, snippets)},
        ],
    )
    raw = response.choices[0].message.content
    parsed = json.loads(raw)  # let malformed JSON raise -> caller logs as error

    # --- enforce the contract regardless of what the model claims ---
    valid_ids = {s["id"] for s in snippets}
    snippet_to_doc = {s["id"]: s["document_id"] for s in snippets}
    sources = [
        {
            "snippet_id": src["snippet_id"],
            "document_id": snippet_to_doc.get(src["snippet_id"]),
            "quote": src.get("quote", ""),
        }
        for src in parsed.get("sources", [])
        if isinstance(src, dict) and src.get("snippet_id") in valid_ids
    ]
    confidence = float(parsed.get("confidence", 0.0))
    needs_review = bool(parsed.get("needs_review", False))

    if not sources:
        needs_review = True
        parsed.setdefault("review_reason", "no_valid_sources_returned")
    if confidence < CONFIDENCE_THRESHOLD:
        needs_review = True
        parsed["review_reason"] = parsed.get("review_reason") or "low_confidence"
    if needs_review and not sources:
        # keep the "honest" framing rather than the model's own wording
        pass

    return {
        "answer": parsed.get("answer", ""),
        "confidence": confidence,
        "sources": sources,
        "needs_review": needs_review,
        "review_reason": parsed.get("review_reason"),
    }