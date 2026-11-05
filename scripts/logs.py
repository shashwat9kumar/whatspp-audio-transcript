"""Logging setup shared by the web app and the command line.

Messages go to the terminal and to logs/app.log. Personal data stays out of the log:
phone numbers and chat names are masked, and transcript text is never logged.
"""

import logging
import time
from logging.handlers import RotatingFileHandler

from scripts import config

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup():
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = RotatingFileHandler(
        config.LOG_DIR / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(level=logging.INFO, format=FORMAT, handlers=[logging.StreamHandler(), log_file])
    # Flask logs every request, including the status poll every 3 seconds. Keep only its warnings.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def mask(text):
    """'918601729176' -> '********9176'. Enough to tell chats apart, not enough to identify anyone."""
    text = str(text)
    return "*" * (len(text) - 4) + text[-4:] if len(text) > 4 else "****"


def seconds_since(start):
    return time.perf_counter() - start
