"""Audio helpers: convert any audio file to WAV and join many WAV files into one.

Every WAV we write has the same format (16 kHz, mono, 16-bit). That is the format
speech models expect, and it lets us join files by simply appending their samples.
"""

import wave
from pathlib import Path

import av  # PyAV: Python bindings to FFmpeg's libraries, no ffmpeg install needed

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # bytes per sample (16-bit)
CHANNELS = 1


def _open_wav_for_writing(path):
    out = wave.open(str(path), "wb")
    out.setnchannels(CHANNELS)
    out.setsampwidth(SAMPLE_WIDTH)
    out.setframerate(SAMPLE_RATE)
    return out


def to_wav(source: Path, target: Path):
    """Decode any audio file (WhatsApp voice notes are OGG/Opus) into a 16 kHz mono WAV."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    with av.open(str(source)) as container, _open_wav_for_writing(target) as out:
        for frame in container.decode(audio=0):
            _write_frames(out, resampler.resample(frame))
        _write_frames(out, resampler.resample(None))  # flush what is left in the resampler


def _write_frames(out, frames):
    for frame in frames:
        # The plane buffer can be padded, so keep only the real samples.
        out.writeframes(bytes(frame.planes[0])[: frame.samples * SAMPLE_WIDTH])


def combine_wavs(sources: list[Path], target: Path, gap_seconds=1.0):
    """Join WAV files end to end, with a short silence between clips."""
    silence = b"\x00" * int(SAMPLE_RATE * gap_seconds) * SAMPLE_WIDTH
    with _open_wav_for_writing(target) as out:
        for index, source in enumerate(sources):
            if index > 0:
                out.writeframes(silence)
            with wave.open(str(source), "rb") as clip:
                out.writeframes(clip.readframes(clip.getnframes()))


def duration(wav_path: Path) -> float:
    """Length of a WAV file in seconds."""
    with wave.open(str(wav_path), "rb") as clip:
        return clip.getnframes() / clip.getframerate()
