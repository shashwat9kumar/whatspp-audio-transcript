"""Speech-to-text with a local Ollama model, then conversion to Hinglish.

Two calls to the same local model:
1. transcribe(): audio -> text, through Ollama's /v1/audio/transcriptions endpoint.
   Gemma writes Hindi speech in Devanagari here and ignores our prompt, so:
2. to_hinglish(): Devanagari -> Roman letters ("kya kar rahe ho"), through /api/chat.
   Words are only re-spelled, never translated.
"""

import re
from pathlib import Path

import requests

from scripts import config

# Only used by models that have no built-in transcription instructions.
PROMPT = (
    "Transcribe this audio exactly as spoken. The speaker may use Hindi, English, "
    "or a mix of both. Do not translate."
)

HINGLISH_INSTRUCTIONS = (
    "You convert Hindi text written in Devanagari into Hinglish: the same words written in "
    "Roman (English) letters, the way Indians type on WhatsApp, e.g. 'kya kar rahe ho'. "
    "Rules: do not translate; keep every word and its order; keep English words in normal "
    "English spelling; keep numbers as digits; output only the converted text."
)

DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def transcribe(wav_path: Path) -> str:
    with open(wav_path, "rb") as audio_file:
        response = requests.post(
            f"{config.OLLAMA_URL}/v1/audio/transcriptions",
            files={"file": (wav_path.name, audio_file, "audio/wav")},
            # No "language" field: the model detects it, which suits mixed Hindi/English speech.
            data={"model": config.OLLAMA_MODEL, "prompt": PROMPT, "response_format": "json"},
            timeout=900,
        )
    if response.status_code == 404:
        raise RuntimeError(
            f"Ollama can't transcribe with '{config.OLLAMA_MODEL}'. Update Ollama to v0.40.12+ "
            f"and run: ollama pull {config.OLLAMA_MODEL}"
        )
    response.raise_for_status()
    return response.json()["text"].strip()


def has_devanagari(text: str) -> bool:
    return bool(DEVANAGARI.search(text))


def to_hinglish(text: str) -> str:
    """Re-spell Devanagari text in Roman letters. Text that is already Roman is returned as is."""
    if not has_devanagari(text):
        return text
    response = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": HINGLISH_INSTRUCTIONS},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "think": False,  # plain conversion, no reasoning needed
            "options": {"temperature": 0},  # same input gives the same output
        },
        timeout=900,
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()
