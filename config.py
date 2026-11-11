# NetSage AI — Configuration
# ─────────────────────────────────────────────
# Configure secrets through environment variables.
# Set MOCK_AI=True to run without any LLM API key.
# ─────────────────────────────────────────────

import os

from dotenv import load_dotenv

load_dotenv()

# ── AI Provider ─────────────────────────────
# Supported: "gemini"  |  "openai"
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini")

# ── Google Gemini ────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── OpenAI (alternative) ─────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── Mock / Offline Mode ──────────────────────
# Set MOCK_AI=True to skip live LLM calls (uses pre-written responses)
MOCK_AI = os.getenv("MOCK_AI", "false").lower() in ("true", "1", "yes")

# ── Flask ────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
DEBUG      = os.getenv("FLASK_DEBUG", "true").lower() in ("true", "1")
PORT       = int(os.getenv("PORT", 5000))
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 1_048_576))
EXPOSE_DIAGNOSIS_INPUTS = os.getenv("EXPOSE_DIAGNOSIS_INPUTS", "false").lower() in ("true", "1", "yes")

if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "netsage-local-development-only"
    else:
        raise RuntimeError("SECRET_KEY must be set when FLASK_DEBUG is disabled.")

# ── Database ─────────────────────────────────
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
DB_PATH  = os.getenv("SQLITE_PATH", str(BASE_DIR / "database" / "netsage.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
