import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
for k in ("WA_TOKEN", "WA_PHONE_NUMBER_ID", "WA_APP_SECRET", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)
