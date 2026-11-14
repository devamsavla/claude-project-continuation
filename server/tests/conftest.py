import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["MEDIA_DIR"] = os.path.join(tempfile.mkdtemp(), "media")
for k in ("WA_TOKEN", "WA_PHONE_NUMBER_ID", "WA_APP_SECRET", "ANTHROPIC_API_KEY", "LLM_API_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN",
          "GOOGLE_CLIENT_ID", "SAFE_BROWSING_KEY"):
    os.environ.pop(k, None)

os.environ["ASK_QUESTIONS"] = "0"  # Mindy's tail questions are tested on their own in test_mind.py

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app import auth
    auth._tries.clear()
    yield
