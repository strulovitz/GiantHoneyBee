"""
varispeed.py — ffmpeg-subprocess 2× time compression for audio.

Ported from HoneycombOfAI/queen_multimedia.py (varispeed_audio function).

Tape-style varispeed: asetrate raises the sample rate (playing faster,
pitch shifts up), then aresample restores the nominal sample rate so
downstream tools see the correct rate. The result is the original audio
at ~2× speed with pitch shifted accordingly — exactly what whisper.cpp
needs for its empirical 2× ceiling (reference_empirical_model_limits.md).

Plan reference: MULTIMEDIA_HIERARCHY_PLAN.md Section 9, 14d.
"""

import subprocess
from pathlib import Path


# Empirical ceiling from reference_empirical_model_limits.md and
# queen_multimedia.py (VARISPEED_RATIO = 2.0). Never exceed this.
MAX_RATIO = 2.0

# Default sample rate for whisper — 16 kHz mono.
_WHISPER_RATE = 16000


def _probe_sample_rate(audio_path: str) -> int:
    """Return the sample rate of audio_path via ffprobe.

    Falls back to _WHISPER_RATE if ffprobe fails or gives no output.
    """
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate",
            "-of", "default=nw=1:nk=1",
            audio_path,
        ],
        capture_output=True,
        text=True,
    )
    raw = r.stdout.strip()
    if raw.isdigit():
        return int(raw)
    return _WHISPER_RATE


def time_compress_audio(
    input_path: str,
    output_path: str,
    ratio: float = 2.0,
) -> None:
    """Compress audio in time by `ratio` via ffmpeg asetrate+aresample.

    Follows the exact pattern from HoneycombOfAI/queen_multimedia.py
    (varispeed_audio): probe the source sample rate, multiply by ratio to
    get the asetrate value, then resample back to the source rate. The final
    output is resampled to 16 kHz mono WAV for whisper compatibility.

    The key: asetrate tells ffmpeg to pretend the samples were recorded at
    a higher rate (so fewer samples per second are played — faster speech).
    aresample then stretches/resamples back to the nominal output rate without
    changing the duration as perceived by the downstream tool.

    Ratio is clamped to MAX_RATIO (2.0) — the empirical whisper.cpp ceiling.

    Parameters
    ----------
    input_path : str
        Path to the source audio file (mp3, wav, ogg, …).
    output_path : str
        Path to the destination .wav file. Parent directory must exist.
    ratio : float
        Speed factor (default 2.0, clamped to 2.0).
    """
    ratio = min(float(ratio), MAX_RATIO)

    # Probe the source sample rate so asetrate is applied correctly.
    # queen_multimedia.py always converts to 16 kHz first (extract_audio),
    # then varispeed; we do it in one pass here for efficiency.
    src_rate = _probe_sample_rate(input_path)
    new_rate = int(src_rate * ratio)

    # asetrate=new_rate  — tells decoder to treat samples as if recorded at
    #                      new_rate Hz; playback at src_rate => 2× faster.
    # aresample=src_rate — resample from new_rate back to src_rate so the
    #                      output has nominal timing at src_rate.
    # ar=16000, ac=1     — final conversion to whisper's expected format.
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", f"asetrate={new_rate},aresample={src_rate}",
            "-ar", str(_WHISPER_RATE),   # resample to 16 kHz for whisper
            "-ac", "1",                  # mono
            output_path,
        ],
        capture_output=True,
        check=True,
    )
