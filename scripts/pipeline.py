"""The full job: download audio -> convert -> transcribe -> translate -> combine.

Run from the command line:
    python -m scripts.pipeline --phone 919876543210 --chat "Family"
"""

import argparse
import logging
import re
import time
from datetime import date, datetime, time as day_time, timedelta

from scripts import audio, chat_files, config, logs, transcribe, translate, whatsapp
from scripts.logs import mask, seconds_since

log = logging.getLogger("pipeline")


DEFAULT_DAYS_BACK = 365


def default_dates():
    """(from, to) as dates: one year ago until today."""
    today = date.today()
    return today - timedelta(days=DEFAULT_DAYS_BACK), today


def run(chat, date_from: date = None, date_to: date = None, progress=lambda message: None):
    """Process the audio messages of one chat sent between date_from and date_to (both included).
    Without dates: the last year. `progress` receives short status messages for the web page."""

    def step(message):
        """Tell both the log and the web page."""
        log.info(message)
        progress(message)

    job_start = time.perf_counter()
    if not whatsapp.is_connected():
        raise RuntimeError("WhatsApp is not connected yet. Link your number first.")

    log.info("Job started for chat %s, transcription model %s", mask(chat), config.OLLAMA_MODEL)
    chat_id = whatsapp.find_chat_id(chat)
    folder = chat_files.folder_for(chat)
    audio_dir, wav_dir, text_dir = folder / "audio", folder / "wav", folder / "transcripts"
    wav_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    default_from, default_to = default_dates()
    date_from, date_to = date_from or default_from, date_to or default_to
    if date_from > date_to:
        raise ValueError("The 'from' date must be before the 'to' date.")
    since = int(datetime.combine(date_from, day_time.min).timestamp())  # start of first day
    until = int(datetime.combine(date_to, day_time.max).timestamp())    # end of last day

    # Step 1: download
    step(f"Step 1/5: downloading audio messages from {date_from} to {date_to}...")
    started = time.perf_counter()
    clips, oldest = whatsapp.download_audios(chat_id, audio_dir, since, until)
    if oldest and oldest > since:
        # WhatsApp only gives a linked device part of the history. Say so instead of
        # silently returning fewer voice notes than the user expects.
        step(f"Note: WhatsApp has only synced this chat back to "
             f"{datetime.fromtimestamp(oldest):%Y-%m-%d}. Older voice notes are not available yet "
             f"(see 'Get older messages' below).")
    if not clips:
        raise ValueError(f"No audio messages were found in this chat between {date_from} and {date_to}.")
    chat_files.save_clips(folder, clips)  # lets translate.py run later without WhatsApp
    step(f"Step 1/5 done: {len(clips)} audio messages ready in {seconds_since(started):.1f}s")
    total = len(clips)

    # Step 2: convert to WAV
    step("Step 2/5: converting audio to WAV...")
    started = time.perf_counter()
    for number, clip in enumerate(clips, start=1):
        clip["wav"] = wav_dir / f"{clip['path'].stem}.wav"
        if clip["wav"].exists():
            log.info("Convert %d/%d: already converted, skipping", number, total)
        else:
            clip_start = time.perf_counter()
            audio.to_wav(clip["path"], clip["wav"])
            log.info("Convert %d/%d: done in %.1fs", number, total, seconds_since(clip_start))
        clip["seconds"] = audio.duration(clip["wav"])
    audio_length = sum(clip["seconds"] for clip in clips)
    step(f"Step 2/5 done: {_minutes(audio_length)} of audio in {seconds_since(started):.1f}s")

    # Step 3: transcribe (the slow part), then make sure the text is Hinglish (Roman letters)
    step("Step 3/5: transcribing...")
    started = time.perf_counter()
    newly_transcribed = 0
    for number, clip in enumerate(clips, start=1):
        stem = clip["path"].stem
        clip["text_file"] = text_dir / f"{stem}.txt"

        if clip["text_file"].exists():  # done in an earlier run
            text = clip["text_file"].read_text(encoding="utf-8")
            if not transcribe.has_devanagari(text):
                log.info("Transcribe %d/%d: already transcribed, skipping", number, total)
                continue
            log.info("Transcribe %d/%d: already transcribed, but still in Devanagari", number, total)
        else:
            step(f"Transcribing {number} of {total} ({clip['seconds']:.0f}s of audio)...")
            clip_start = time.perf_counter()
            text = transcribe.transcribe(clip["wav"])
            # Save right away, so a failure in the next step doesn't lose the slow transcription.
            clip["text_file"].write_text(text, encoding="utf-8")
            newly_transcribed += 1
            # Only the length of the text is logged, never the text itself (it is private).
            log.info("Transcribe %d/%d: %d characters in %.1fs", number, total, len(text), seconds_since(clip_start))

        if transcribe.has_devanagari(text):
            clip_start = time.perf_counter()
            # Keep the original next to it, so the conversion can be checked against it.
            original = text_dir / f"{stem}.devanagari.txt"
            if not original.exists():  # never overwrite the first, untouched version
                original.write_text(text, encoding="utf-8")
            text = transcribe.to_hinglish(text)
            clip["text_file"].write_text(text, encoding="utf-8")
            log.info("Hinglish %d/%d: converted from Devanagari in %.1fs", number, total, seconds_since(clip_start))
    step(f"Step 3/5 done: {newly_transcribed} new, {total - newly_transcribed} already done, "
         f"in {seconds_since(started):.1f}s")

    # Step 4: translate to English (also writes combined_transcript_english.txt)
    step("Step 4/5: translating to English...")
    started = time.perf_counter()
    combined_english = translate.translate_chat(folder, progress=step)
    step(f"Step 4/5 done in {seconds_since(started):.1f}s")

    # Step 5: combine
    step("Step 5/5: combining audio and text...")
    started = time.perf_counter()
    combined_audio = folder / "combined_audio.wav"
    audio.combine_wavs([clip["wav"] for clip in clips], combined_audio)
    combined_text = chat_files.write_combined_text(
        folder, chat_files.load_clips(folder), ".txt", "combined_transcript.txt"
    )
    step(f"Step 5/5 done in {seconds_since(started):.1f}s")

    step(f"All done: {total} audio messages, {_minutes(audio_length)} of audio, "
         f"total time {seconds_since(job_start):.1f}s")
    # File names only: the folder is named after the chat, which may be a phone number.
    log.info("Output written: %s, %s, %s", combined_audio.name, combined_text.name, combined_english.name)
    return {"count": total, "folder": folder, "audio": combined_audio,
            "transcript": combined_text, "english": combined_english}


def _minutes(seconds):
    return f"{int(seconds // 60)}m {int(seconds % 60)}s"


def main():
    parser = argparse.ArgumentParser(description="Transcribe all audio messages in a WhatsApp chat.")
    parser.add_argument("--phone", required=True, help="Your WhatsApp number with country code")
    parser.add_argument("--chat", required=True, help="Other person's number, or the chat/group name")
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat,
                        help="First day, YYYY-MM-DD (default: one year ago)")
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat,
                        help="Last day, YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    logs.setup()

    result = whatsapp.connect(re.sub(r"\D", "", args.phone))
    if result["pairing_code"]:
        print(f"On your phone: WhatsApp > Linked devices > Link with phone number > enter {result['pairing_code']}")
        while not whatsapp.is_connected():
            time.sleep(3)
    print("WhatsApp connected.")

    output = run(args.chat, args.date_from, args.date_to)
    print(f"Combined audio: {output['audio']}")
    print(f"Combined transcript: {output['transcript']}")
    print(f"English transcript: {output['english']}")


if __name__ == "__main__":
    main()
