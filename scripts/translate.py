"""Translate a chat's transcripts into English with the local Ollama model.

Runs as part of the pipeline, or on its own for a chat that is already transcribed
(no WhatsApp connection needed):
    python -m scripts.translate --chat 918601729176
"""

import argparse
import logging
import time
from pathlib import Path

import requests

from scripts import chat_files, config, logs
from scripts.logs import seconds_since

log = logging.getLogger("translate")

INSTRUCTIONS = (
    "Translate the user's text into natural, fluent English. The text is a transcript of a "
    "WhatsApp voice note in Hindi, English, or a mix of both. Rules: translate everything, "
    "do not summarize or leave anything out; keep names, places, amounts and numbers exactly; "
    "keep the speaker's tone (casual stays casual); output only the translation."
)


def to_english(text: str) -> str:
    response = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0},  # same input gives the same output
        },
        timeout=900,
    )
    response.raise_for_status()
    return response.json()["message"]["content"].strip()


def translate_chat(folder: Path, progress=lambda message: None) -> Path:
    """Write transcripts/<stem>.en.txt for every clip, then combined_transcript_english.txt.

    Translates the original transcript: the model's Hindi-script output if there is one,
    otherwise the transcript as written. Clips already translated are skipped.
    """
    clips = chat_files.load_clips(folder)
    text_dir = folder / "transcripts"
    total, new = len(clips), 0

    for number, clip in enumerate(clips, start=1):
        target = text_dir / f"{clip['stem']}.en.txt"
        if target.exists():
            log.info("Translate %d/%d: already translated, skipping", number, total)
            continue

        original = text_dir / f"{clip['stem']}.devanagari.txt"
        source = original if original.exists() else text_dir / f"{clip['stem']}.txt"
        progress(f"Translating {number} of {total}...")
        started = time.perf_counter()
        english = to_english(source.read_text(encoding="utf-8"))
        target.write_text(english, encoding="utf-8")
        new += 1
        # Lengths only: the text itself is private.
        log.info("Translate %d/%d: %d characters from %s in %.1fs",
                 number, total, len(english), source.name.split(".", 1)[1], seconds_since(started))

    log.info("Translated %d new, %d already done", new, total - new)
    return chat_files.write_combined_text(folder, clips, ".en.txt", "combined_transcript_english.txt")


def main():
    parser = argparse.ArgumentParser(description="Translate a transcribed chat into English.")
    parser.add_argument("--chat", required=True, help="The same number or chat name used for transcription")
    args = parser.parse_args()
    logs.setup()

    started = time.perf_counter()
    try:
        output = translate_chat(chat_files.folder_for(args.chat), progress=log.info)
    except FileNotFoundError as error:
        raise SystemExit(str(error))  # plain message, no traceback
    log.info("Done in %.1fs", seconds_since(started))
    print(f"English transcript: {output}")


if __name__ == "__main__":
    main()
