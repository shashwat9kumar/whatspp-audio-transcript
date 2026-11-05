"""Small web UI on top of the scripts. Start with:  python app.py  then open http://127.0.0.1:5050"""

import logging
import re
import threading
from datetime import date

import requests
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from scripts import config, logs, pipeline, whatsapp
from scripts.logs import mask

logs.setup()
log = logging.getLogger("app")

app = Flask(__name__)

# One job at a time is enough for a personal tool, so plain module-level state is fine.
job = {"running": False, "messages": [], "result": None, "error": None}


@app.errorhandler(requests.ConnectionError)
def services_down(error):
    message = "Can't reach WAHA. Is the container running? (docker compose up -d)"
    log.error("%s Details: %s", message, error)
    return render_template("index.html", connected=False, error=message, job=job), 503


@app.errorhandler(RuntimeError)
def wrong_service(error):
    log.error("%s", error)
    return render_template("index.html", connected=False, error=str(error), job=job), 503


@app.get("/")
def index():
    session = whatsapp.get_session()
    connected = bool(session and session["status"] == "WORKING")
    date_from, date_to = pipeline.default_dates()
    return render_template(
        "index.html", connected=connected, linked_number=whatsapp.linked_number(session), job=job,
        date_from=date_from.isoformat(), date_to=date_to.isoformat(),
    )


@app.post("/connect")
def connect():
    phone = re.sub(r"\D", "", request.form.get("phone", ""))
    if not 8 <= len(phone) <= 15:
        log.warning("Rejected phone number with %d digits", len(phone))
        return render_template("index.html", connected=False, error="Enter your number with country code.", job=job)
    result = whatsapp.connect(phone)
    if result["status"] == "WORKING":
        return redirect(url_for("index"))
    return render_template("pairing.html", code=result["pairing_code"])


@app.get("/connection-status")
def connection_status():
    return jsonify(connected=whatsapp.is_connected())


@app.post("/start")
def start():
    chat = request.form.get("chat", "").strip()
    if not chat or len(chat) > 100:
        abort(400, "Enter a phone number or chat name.")
    try:
        date_from = date.fromisoformat(request.form["date_from"])
        date_to = date.fromisoformat(request.form["date_to"])
    except (KeyError, ValueError):
        abort(400, "Enter valid dates.")
    if job["running"]:
        log.warning("Start ignored: a job is already running")
    else:
        log.info("Starting job for chat %s, %s to %s", mask(chat), date_from, date_to)
        job.update(running=True, messages=[], result=None, error=None)
        threading.Thread(target=_run_job, args=(chat, date_from, date_to), daemon=True).start()
    return redirect(url_for("index"))


@app.post("/relink")
def relink():
    """Unlink and link again, so WhatsApp sends the chat history again (see docker-compose.yml)."""
    if job["running"]:
        abort(409, "Wait for the running job to finish first.")
    whatsapp.logout()
    return redirect(url_for("index"))


@app.get("/job-status")
def job_status():
    return jsonify(running=job["running"], messages=job["messages"], error=job["error"], done=bool(job["result"]))


@app.get("/files/<path:name>")
def files(name):
    # send_from_directory refuses paths that escape DATA_DIR
    return send_from_directory(config.DATA_DIR, name, as_attachment=True)


def _run_job(chat, date_from, date_to):
    try:
        result = pipeline.run(chat, date_from, date_to, progress=job["messages"].append)
        folder = result["folder"].relative_to(config.DATA_DIR).as_posix()
        job["result"] = {
            "count": result["count"],
            "audio": f"{folder}/{result['audio'].name}",
            "transcript": f"{folder}/{result['transcript'].name}",
            "english": f"{folder}/{result['english'].name}",
        }
    except Exception as error:  # show any failure to the user instead of a silent dead thread
        log.exception("Job failed")  # full traceback goes to the log for debugging
        job["error"] = str(error)
    finally:
        job["running"] = False


if __name__ == "__main__":
    log.info("Web app on http://127.0.0.1:%d, logging to %s", config.APP_PORT, config.LOG_DIR / "app.log")
    # Not 5000: macOS uses that port for AirPlay Receiver.
    app.run(host="127.0.0.1", port=config.APP_PORT, debug=False)
