"""Talks to WAHA (WhatsApp HTTP API): link the account, find the chat, download audio messages."""

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import requests

from scripts import config
from scripts.logs import mask, seconds_since

log = logging.getLogger("whatsapp")

SESSION = config.WAHA_SESSION
HEADERS = {"X-Api-Key": config.WAHA_API_KEY}
PAGE_SIZE = 100


def _request(method, path, timeout=120, **kwargs):
    for attempt in (1, 2):
        try:
            response = requests.request(
                method, config.WAHA_URL + path, headers=HEADERS, timeout=timeout, **kwargs
            )
            break
        except requests.Timeout:
            # WAHA can be slow right after it starts while it syncs with WhatsApp. Try once more.
            if attempt == 2:
                raise
            log.warning("WAHA did not answer within %ds, retrying once", timeout)
    response.raise_for_status()
    if not response.content:
        return None
    if "json" not in response.headers.get("Content-Type", ""):
        raise RuntimeError(f"{config.WAHA_URL} did not answer like WAHA. Check WAHA_URL in .env.")
    return response.json()


def _get_all_pages(path, params=None):
    """Call a list endpoint page by page until it returns an empty page."""
    items, offset = [], 0
    while True:
        started = time.perf_counter()
        page = _request("GET", path, params={**(params or {}), "limit": PAGE_SIZE, "offset": offset})
        log.info("Fetched page at offset %d: %d items in %.1fs", offset, len(page or []), seconds_since(started))
        if not page:
            return items
        items.extend(page)
        offset += PAGE_SIZE


# ---------- Linking the WhatsApp account ----------

def get_session():
    """Return the WAHA session info, or None if the session does not exist yet."""
    try:
        return _request("GET", f"/api/sessions/{SESSION}")
    except requests.HTTPError as error:
        if error.response.status_code == 404:
            return None
        raise


def _wait_for_status(wanted, seconds=30):
    for _ in range(seconds):
        session = get_session()
        if session and session["status"] in wanted:
            return session
        time.sleep(1)
    raise TimeoutError("WhatsApp session did not become ready. Check the WAHA container logs.")


def connect(phone_number):
    """Start the session and, if not linked yet, ask WhatsApp for a pairing code.

    Returns a dict: {"status": ..., "linked_number": ..., "pairing_code": ...}
    """
    session = get_session()
    log.info("Connecting %s. Session '%s' is %s", mask(phone_number), SESSION,
             session["status"] if session else "not created yet")
    if session is None:
        _request("POST", "/api/sessions", json={"name": SESSION, "start": True})
    elif session["status"] == "STOPPED":
        _request("POST", f"/api/sessions/{SESSION}/start")
    elif session["status"] == "FAILED":
        _request("POST", f"/api/sessions/{SESSION}/restart")

    session = _wait_for_status({"WORKING", "SCAN_QR_CODE"})
    if session["status"] == "WORKING":
        log.info("Already linked as %s", mask(linked_number(session)))
        return {"status": "WORKING", "linked_number": linked_number(session), "pairing_code": None}

    code = _request("POST", f"/api/{SESSION}/auth/request-code", json={"phoneNumber": phone_number})
    log.info("Pairing code issued. Waiting for the phone to link")  # the code itself is a secret
    return {"status": session["status"], "linked_number": None, "pairing_code": code["code"]}


def linked_number(session):
    """Phone number of the linked account, e.g. '919876543210', or None."""
    me = (session or {}).get("me") or {}
    return me.get("id", "").split("@")[0] or None


def is_connected():
    session = get_session()
    return bool(session and session["status"] == "WORKING")


def logout():
    """Unlink this app from WhatsApp. Linking again makes WhatsApp send the chat history again,
    using the history settings in docker-compose.yml (they only apply when a device is linked)."""
    _request("POST", f"/api/sessions/{SESSION}/logout")
    log.info("Logged out of WhatsApp. Link again to sync history")


# ---------- Finding the chat ----------

def find_chat_id(chat):
    """Accept a phone number ('+91 98765 43210') or a chat/group name ('Family')."""
    if re.fullmatch(r"[+\d\s()-]+", chat):
        chat_id = re.sub(r"\D", "", chat) + "@c.us"
        log.info("Chat given as a phone number: %s", mask(chat_id))
        return chat_id

    start = time.perf_counter()
    chats = _get_all_pages(f"/api/{SESSION}/chats/overview")
    wanted = chat.casefold()
    exact = [c for c in chats if (c.get("name") or "").casefold() == wanted]
    partial = [c for c in chats if wanted in (c.get("name") or "").casefold()]
    matches = exact or partial
    log.info("Searched %d chats by name in %.1fs: %d match(es)", len(chats), seconds_since(start), len(matches))

    if len(matches) == 1:
        log.info("Using chat %s", mask(matches[0]["id"]))
        return matches[0]["id"]
    if not matches:
        raise ValueError(f"No chat named '{chat}' was found.")
    names = ", ".join(c["name"] for c in matches[:5])
    raise ValueError(f"'{chat}' matches several chats ({names}). Please type the full name.")


# ---------- Downloading audio ----------

def download_audios(chat_id, audio_dir: Path, since: int, until: int):
    """Download every audio message in the chat sent between `since` and `until`
    (Unix timestamps, both included), oldest first.

    Files that already exist are not downloaded again.
    Returns (clips, oldest_timestamp): clips is a list of dicts {"path", "timestamp", "sender"};
    oldest_timestamp is the oldest message WhatsApp has synced for this chat (None if empty).
    """
    audio_dir.mkdir(parents=True, exist_ok=True)
    messages_path = f"/api/{SESSION}/chats/{quote(chat_id, safe='')}/messages"

    # 1. List ALL messages WITHOUT media, then filter by date here. Listing is fast (~0.1s per
    #    100 messages), and seeing every message tells us how far back the history goes.
    #    With media on, WAHA downloads every voice note on a page before it answers,
    #    which can take minutes and time out. The audio mimetype is included either way.
    start = time.perf_counter()
    messages = _get_all_pages(messages_path, {"downloadMedia": "false"})
    oldest = min((m["timestamp"] for m in messages), default=None)
    audio_messages = [m for m in messages if _is_audio(m) and since <= m["timestamp"] <= until]
    audio_messages.sort(key=lambda m: m["timestamp"])
    log.info("Read %d messages in %.1fs (oldest from %s): %d are audio in the chosen dates",
             len(messages), seconds_since(start), _date(oldest), len(audio_messages))

    # 2. Fetch media one message at a time, and only for files we don't have yet.
    clips = []
    for number, message in enumerate(audio_messages, start=1):
        path = audio_dir / _file_name(message)
        label = f"Audio {number}/{len(audio_messages)} ({path.name})"

        if path.exists():
            log.info("%s: already downloaded, skipping", label)
        else:
            started = time.perf_counter()
            full = _request(
                "GET", f"{messages_path}/{quote(message['id'], safe='')}",
                params={"downloadMedia": "true"}, timeout=300,
            )
            url = (full.get("media") or {}).get("url")
            if not url:
                # WhatsApp deletes old media from its servers, so some voice notes can't be fetched.
                log.warning("%s: skipped, WhatsApp no longer has this media", label)
                continue
            _download_media(url, path)
            log.info("%s: downloaded %.0f KB in %.1fs", label, path.stat().st_size / 1024, seconds_since(started))

        sender = "Me" if message.get("fromMe") else (message.get("participant") or message.get("from") or "")
        clips.append({"path": path, "timestamp": message["timestamp"], "sender": sender.split("@")[0]})
    return clips, oldest


def _date(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "-"


def _download_media(url, path: Path):
    """Save one media file from WAHA.

    WAHA builds media links from its own address, which may not be where we reach it
    (e.g. it says localhost:3000 while we use localhost:3010). So we keep only the
    path of the link and always fetch from WAHA_URL. This also makes sure the API key
    is never sent to any other server.
    """
    response = requests.get(config.WAHA_URL + urlsplit(url).path, headers=HEADERS, timeout=120)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if not content_type.startswith(("audio/", "application/octet-stream")):
        raise RuntimeError(f"Expected audio from WAHA but got '{content_type}'. Check WAHA_URL in .env.")
    path.write_bytes(response.content)


def _is_audio(message):
    media = message.get("media") or {}
    return message.get("hasMedia") and (media.get("mimetype") or "").startswith("audio")


def _file_name(message):
    """Timestamp first so files sort in time order. Message id keeps names unique and stable."""
    safe_id = re.sub(r"\W", "", message["id"].split("_")[-1])[:32]
    extension = ".ogg" if "ogg" in message["media"]["mimetype"] else ".audio"
    return f"{message['timestamp']}_{safe_id}{extension}"
