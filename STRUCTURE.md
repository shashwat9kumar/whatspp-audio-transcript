# Project structure

```
whatsapp-audio-transcript/
├── app.py                 Web UI (Flask). Forms + background job. No business logic.
├── scripts/               All the real work. Each file does one thing.
│   ├── config.py          Reads settings from .env
│   ├── logs.py            Logging setup (terminal + logs/app.log) and number masking
│   ├── whatsapp.py        WAHA API: link account, find chat, download audio
│   ├── audio.py           Convert audio to WAV, join WAV files
│   ├── transcribe.py      Send one WAV to Ollama, get text back; re-spell Hindi script as Hinglish
│   ├── translate.py       Translate a chat's transcripts to English. Also a command-line entry point.
│   ├── chat_files.py      Chat folder layout, clips.json, joining per-clip texts into one file
│   └── pipeline.py        Runs the steps in order. Also a command-line entry point.
├── templates/
│   ├── base.html          Page layout and CSS
│   ├── index.html         Step 1 (link number) and step 2 (choose chat + results)
│   └── pairing.html       Shows the pairing code, waits for the phone to link
├── docker-compose.yml     Runs WAHA locally on port 3010
├── requirements.txt       Python packages
├── .env.example           Settings template (copy to .env)
├── README.md              Full guide with diagrams: architecture, flows, setup, config, troubleshooting
├── PRODUCT.md             What the app does and how to use it
├── STRUCTURE.md           This file
├── DECISIONS_LOG.md       Every decision and change, for review
├── data/                  Created at runtime; one folder per chat (git-ignored)
└── logs/app.log           Created at runtime; what happened and how long each step took (git-ignored)
```

## How the pieces connect
```
Browser ──> app.py ──> scripts/pipeline.py
                          ├─ whatsapp.py   ──HTTP──> WAHA (Docker)  ──> WhatsApp
                          ├─ audio.py      (PyAV, in-process)
                          └─ transcribe.py ──HTTP──> Ollama (local)
```

## Flow of one job
1. `whatsapp.find_chat_id` turns a number or chat name into a WhatsApp chat id.
2. `whatsapp.download_audios` pages through all messages and saves the audio ones to `data/<chat>/audio/`.
3. `audio.to_wav` converts each file to 16 kHz mono WAV in `wav/`.
4. `transcribe.transcribe` sends each WAV to Ollama, and `transcribe.to_hinglish` re-spells any Hindi script. The text is saved in `transcripts/`.
5. `translate.translate_chat` translates each original transcript to English (`<clip>.en.txt`) and writes `combined_transcript_english.txt`.
6. `audio.combine_wavs` and `chat_files.write_combined_text` write the combined audio and Hinglish transcript.

Steps 2 to 5 skip files that already exist, so a re-run continues where the last one stopped.
