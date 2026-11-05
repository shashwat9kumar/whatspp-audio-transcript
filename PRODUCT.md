# Product: WhatsApp Audio Transcript

## What it does
A small local web app. You give it:
1. **Your WhatsApp number** – used to link your account (like WhatsApp Web).
2. **Another number or a chat/group name** – the chat to process.

It then:
1. Downloads every audio message (voice notes and audio files) in that chat within a date range. The default range is the **last 365 days**, and you can change it in the page.
2. Transcribes each one with a **local Ollama model** into **Hinglish**: Hindi words in Roman letters ("kya kar rahe ho"), English words in English. Never translated.
3. Translates each original transcript into **English** with the same local model.
4. Joins all clips, oldest first, into **one audio file** (`combined_audio.wav`).
5. Joins all transcripts into **one text file** (`combined_transcript.txt`, Hinglish) and all translations into another (`combined_transcript_english.txt`). Each part is labelled with date, time, and sender.

Everything runs on your computer. Audio never goes to a cloud service.

## Requirements
| Need | Why | Install |
|---|---|---|
| Python 3.10+ | runs the app | already installed |
| Docker | runs WAHA, the WhatsApp API | Docker Desktop |
| Ollama **v0.40.12 or newer** | speech-to-text via `/v1/audio/transcriptions` | `brew upgrade ollama` or download from ollama.com |
| An Ollama model with audio input | does the transcription | `ollama pull gemma4:e4b` |

No separate ffmpeg install is needed. The `av` Python package bundles the decoders.

## Setup
```bash
cp .env.example .env              # then set WAHA_API_KEY to a long random string
docker compose up -d              # starts WAHA on http://localhost:3010
ollama pull gemma4:e4b            # speech-capable model
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Use it
**Web app**
```bash
.venv/bin/python app.py           # open http://127.0.0.1:5050 (change with APP_PORT in .env)
```
1. Enter your number with country code (e.g. `919876543210`) and press **Get pairing code**.
2. On your phone: WhatsApp > Settings > Linked devices > Link a device > *Link with phone number instead*, then type the code.
3. Enter the other person's number or the chat name. Check the **From / to** dates (one year ago to today by default) and press **Transcribe all audio**.
4. Download the combined audio and transcript when it finishes. The combined files cover only the chosen dates.

**Command line (same scripts, no browser)**
```bash
.venv/bin/python -m scripts.pipeline --phone 919876543210 --chat "Family"                       # last year
.venv/bin/python -m scripts.pipeline --phone 919876543210 --chat "Family" --from 2025-01-01 --to 2025-06-30
```

### Getting older voice notes
WhatsApp decides how much history it sends to a linked device, and it often sends only the last few weeks. If the page says *"WhatsApp has only synced this chat back to …"*:
1. Press **Unlink and link again** under *Get older messages*, then link with a new pairing code.
2. On linking, the app asks WhatsApp for a full history sync of the last `HISTORY_SYNC_DAYS` days (365 by default, set in `.env`). For older voice notes, raise that number and run `docker-compose up --detach` before linking again.
3. Keep your phone online. WhatsApp sends the history in the background, which can take several minutes for big chats. Run the job again afterwards.

Already processed voice notes stay on disk and are not done again.

**Translate only** (for a chat that is already transcribed; WhatsApp is not needed)
```bash
.venv/bin/python -m scripts.translate --chat "Family"
```
It only translates clips without an English version yet. To redo one, delete its `.en.txt` file and run it again.

## Output
```
data/<chat name>/
  audio/                    original files from WhatsApp (.ogg)
  wav/                      each clip converted to 16 kHz mono WAV
  clips.json                time and sender of each clip (used by the translate script)
  transcripts/              one .txt per clip, in Hinglish
                            (+ <clip>.devanagari.txt: the model's original Hindi-script text, when it wrote one)
                            (+ <clip>.en.txt: English translation)
  combined_audio.wav        all clips joined, 1 s silence between them
  combined_transcript.txt   all transcripts joined, with time and sender
  combined_transcript_english.txt   all English translations joined, same layout
```
Running the same chat again only downloads and transcribes new messages.

## Limits
- **Old media can be missing.** WhatsApp removes old media from its servers. The app skips audio it cannot download and prints a note.
- **History depth is up to WhatsApp.** The app asks for a full sync (see *Getting older voice notes*), but WhatsApp can still send less, and the settings for this are marked experimental by WAHA. The page always tells you the oldest date it actually received.
- **Transcription quality** depends on the model. If `gemma4:e4b` is weak on your audio, try a bigger tag (`gemma4:12b`) by changing `OLLAMA_MODEL` in `.env`.
- **Unofficial API.** WAHA works like WhatsApp Web. WhatsApp's official Business API cannot read the history of personal chats. Use it only on your own account.
- **One job at a time** in the web app. It is a personal tool, not a multi-user service.
