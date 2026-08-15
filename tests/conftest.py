"""Sets isolated storage paths before anything imports app.main.

Runs at collection time (module-level code executes on import), which is
before test_api.py's `from app.main import app` — so database.py, search.py
and llm.py all pick up these paths/values via os.getenv() at their own
import time.
"""
import os
import tempfile

_tmp_dir = tempfile.mkdtemp(prefix="kb_ci_")
os.environ.setdefault("DATABASE_PATH", os.path.join(_tmp_dir, "knowledge.db"))
os.environ.setdefault("CHROMA_PATH", os.path.join(_tmp_dir, "chroma"))
# Auto-seed is a demo/production convenience (see app/main.py) — disabled
# here so the empty-KB test genuinely exercises the empty-KB code path.
os.environ.setdefault("AUTO_SEED_DEMO_DATA", "false")
# No real LLM key in CI on purpose: tests verify the system fails safe
# (needs_review=true, no crash) rather than exercising the real model.
os.environ.setdefault("OPENAI_API_KEY", "")
