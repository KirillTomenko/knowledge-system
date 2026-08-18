"""Hybrid retrieval: BM25 keyword search + ChromaDB vector search.

Design choice for the "team knowledge" variant: keyword search alone
misses paraphrased questions ("how do I reply to an angry client?" vs
a document titled "Escalation policy"); vector search alone can miss
exact terms/codes/IDs that matter in internal docs. Combining both and
merging by rank is the stronger, more production-appropriate option —
and if the vector backend is ever unavailable, the system degrades
gracefully to keyword-only rather than failing.
"""
import os
import re
from typing import List, Dict

from rank_bm25 import BM25Okapi

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions
    _CHROMA_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _CHROMA_AVAILABLE = False

TOP_K = int(os.getenv("TOP_K", "5"))
CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]+")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class HybridSearch:
    """Rebuilt from the current DB snippets on each app startup / reindex.

    Kept in-memory + a persistent Chroma collection on disk, so restart
    is cheap and there is no separate background indexing job to manage
    for a project this size.
    """

    def __init__(self):
        self._snippets: List[Dict] = []
        self._bm25 = None
        self._chroma_collection = None
        self._chroma_ok = False
        if _CHROMA_AVAILABLE and OPENAI_API_KEY:
            try:
                client = chromadb.PersistentClient(
                    path=CHROMA_PATH,
                    settings=Settings(anonymized_telemetry=False),
                )
                ef = embedding_functions.OpenAIEmbeddingFunction(
                    api_key=OPENAI_API_KEY,
                    api_base=OPENAI_BASE_URL,
                    model_name="text-embedding-3-small",
                )
                self._chroma_collection = client.get_or_create_collection(
                    name="kb_snippets", embedding_function=ef
                )
                self._chroma_ok = True
            except Exception as e:  
                # Production behavior: don't crash the app if the vector
                # backend is misconfigured — fall back to keyword-only.
                print(f"[Chroma] initialization error: {e}")
                self._chroma_ok = False

    def reindex(self, snippets: List[Dict]) -> None:
        self._snippets = snippets
        if not snippets:
            # Nothing indexed yet (fresh DB) — BM25Okapi can't build an
            # index over zero documents, so skip it; search() short-circuits
            # on empty self._snippets anyway.
            self._bm25 = None
            return

        corpus = [_tokenize(s["snippet_text"]) for s in snippets]
        self._bm25 = BM25Okapi(corpus)

        if self._chroma_ok and snippets:
            try:
                self._chroma_collection.delete(
                    ids=self._chroma_collection.get()["ids"] or []
                )
                self._chroma_collection.add(
                    ids=[s["id"] for s in snippets],
                    documents=[s["snippet_text"] for s in snippets],
                    metadatas=[{"document_id": s["document_id"]} for s in snippets],
                )
            except Exception as e:
                print(f"[Chroma] reindex error: {e}")
                self._chroma_ok = False

    def search(self, question: str, top_k: int = None) -> List[Dict]:
        top_k = top_k or TOP_K
        if not self._snippets:
            return []

        # --- keyword ranking ---
        # Note: BM25 scores can be negative on small corpora (a term that
        # appears in most documents gets negative IDF) — rank order still
        # matters, so we don't filter by score sign, only take the top_k.
        scores = self._bm25.get_scores(_tokenize(question))
        keyword_ranked = sorted(
            range(len(self._snippets)), key=lambda i: scores[i], reverse=True
        )[:top_k]
        keyword_ids = [self._snippets[i]["id"] for i in keyword_ranked]

        # --- vector ranking (if available) ---
        vector_ids: List[str] = []
        if self._chroma_ok:
            try:
                result = self._chroma_collection.query(
                    query_texts=[question], n_results=min(top_k, len(self._snippets))
                )
                vector_ids = result.get("ids", [[]])[0]
            except Exception as e:
                print(f"[Chroma] search error: {e}")
                vector_ids = []

        # --- merge by reciprocal rank fusion ---
        rrf_scores: Dict[str, float] = {}
        for rank, sid in enumerate(keyword_ids):
            rrf_scores[sid] = rrf_scores.get(sid, 0) + 1.0 / (60 + rank)
        for rank, sid in enumerate(vector_ids):
            rrf_scores[sid] = rrf_scores.get(sid, 0) + 1.0 / (60 + rank)

        by_id = {s["id"]: s for s in self._snippets}
        merged = sorted(rrf_scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [by_id[sid] for sid, _ in merged if sid in by_id]