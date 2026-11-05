"""All settings in one place. Values come from environment variables or the .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

# WAHA = self-hosted WhatsApp HTTP API (runs in Docker, see docker-compose.yml)
WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3010").rstrip("/")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")

# Ollama runs locally and does the speech-to-text
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

# Port for the web app (http://127.0.0.1:<port>)
APP_PORT = int(os.getenv("APP_PORT", "5050"))

# Where downloaded audio, transcripts and combined files are written
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_DIR / "data")).resolve()

# Where logs/app.log is written
LOG_DIR = Path(os.getenv("LOG_DIR", PROJECT_DIR / "logs")).resolve()
