"""Where a chat's files live, and how per-clip texts are joined into one file.

Layout of data/<chat>/:
    clips.json                       list of clips: file stem, time, sender
    transcripts/<stem>.txt           Hinglish transcript
    transcripts/<stem>.devanagari.txt  model's original output, if it was in Hindi script
    transcripts/<stem>.en.txt        English translation
"""

import json
import re
from datetime import datetime
from pathlib import Path

from scripts import config


def folder_for(chat) -> Path:
    """data/<chat> with unsafe characters replaced, e.g. 'My Family!' -> data/My_Family"""
    return config.DATA_DIR / (re.sub(r"[^\w-]+", "_", chat).strip("_")[:60] or "chat")


def save_clips(folder: Path, clips):
    """Remember time and sender of each clip, so later scripts can work without WhatsApp."""
    rows = [{"stem": c["path"].stem, "timestamp": c["timestamp"], "sender": c["sender"]} for c in clips]
    (folder / "clips.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


def load_clips(folder: Path):
    path = folder / "clips.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run the transcription for this chat first.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_combined_text(folder: Path, clips, suffix: str, out_name: str) -> Path:
    """Join transcripts/<stem><suffix> of every clip into one file, each part headed by time and sender."""
    parts = []
    for clip in clips:
        when = datetime.fromtimestamp(clip["timestamp"]).strftime("%Y-%m-%d %H:%M")
        text = (folder / "transcripts" / f"{clip['stem']}{suffix}").read_text(encoding="utf-8")
        parts.append(f"[{when}] {clip['sender']}:\n{text}\n")
    out = folder / out_name
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
