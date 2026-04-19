"""
audio_cut.py — Temporal Grid A + Grid B audio cut for GiantHoneyBee.

Ported from HoneycombOfAI/queen_multimedia.py (section_grid pattern),
adapted to the 8-piece fixed-shape cut required by the plan (Section 14d,
14f, 5). Unlike queen_multimedia.py which iterates over sliding 60-second
windows, this module produces exactly 8 children per cut (4 Grid A + 4
Grid B), sized to cover the full duration.

Grid A — 4 non-overlapping equal sections covering [0, duration]:
    grid_a_sec_1: [0,           dur/4)
    grid_a_sec_2: [dur/4,       dur/2)
    grid_a_sec_3: [dur/2,       3*dur/4)
    grid_a_sec_4: [3*dur/4,     dur)

Grid B — 4 offset sections each the same length as Grid A sections,
centered on Grid A section boundaries (i.e. half a section_len offset):
    grid_b_sec_1: [dur/8,       3*dur/8)
    grid_b_sec_2: [3*dur/8,     5*dur/8)
    grid_b_sec_3: [5*dur/8,     7*dur/8)
    grid_b_sec_4: [7*dur/8,     dur)   (last one clamps to dur)

This ensures Grid B sections straddle the Grid A section boundaries, so
features at the boundaries are captured by at least one Grid B section —
exactly the Chapter 12 principle.

All sections are extracted as 16 kHz mono WAV (safe for whisper-cli).

Plan reference: MULTIMEDIA_HIERARCHY_PLAN.md Sections 5, 14d, 14f.
"""

import subprocess
import tempfile
from pathlib import Path


# Minimum slice duration below which whisper output is unreliable.
# From Section 14d: "pass-through rule" — tiers skip the cut when the
# piece is too short.
MIN_SLICE_SEC = 5.0


def should_cut(duration: float) -> bool:
    """Return True if this piece is long enough to be worth cutting.

    A False result means the caller should skip the cut and return the
    gestalt as the final paragraph (pass-through, no children).
    """
    return duration >= MIN_SLICE_SEC


def duration_of(audio_path: str) -> float:
    """Return the duration of audio_path in seconds via ffprobe."""
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            audio_path,
        ],
        capture_output=True,
        text=True,
    )
    raw = r.stdout.strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    raise RuntimeError(
        f"duration_of: could not parse duration from ffprobe output "
        f"for {audio_path!r}. ffprobe stdout={r.stdout!r} stderr={r.stderr!r}"
    )


def _extract_wav_section(
    audio_bytes: bytes,
    start: float,
    length: float,
    src_suffix: str = ".mp3",
) -> bytes:
    """Extract [start, start+length) from audio_bytes and return WAV bytes.

    Uses a temp file for input (bytes -> file) and a temp file for output
    (file -> bytes), keeping everything in /tmp.

    Output is always 16 kHz mono WAV for whisper compatibility.
    """
    with tempfile.NamedTemporaryFile(suffix=src_suffix, delete=False) as f_in:
        f_in.write(audio_bytes)
        src_path = f_in.name

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_out:
        dst_path = f_out.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{start:.6f}",
                "-i", src_path,
                "-t", f"{length:.6f}",
                "-ac", "1",
                "-ar", "16000",
                dst_path,
            ],
            capture_output=True,
            check=True,
        )
        return Path(dst_path).read_bytes()
    finally:
        import os
        for p in (src_path, dst_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def cut_grid_ab_temporal(
    audio_bytes: bytes,
    duration_sec: float,
    src_suffix: str = ".mp3",
) -> list[tuple[str, bytes]]:
    """Cut audio_bytes into 8 Grid A + Grid B temporal sections.

    Parameters
    ----------
    audio_bytes : bytes
        Raw bytes of the audio file (mp3, wav, etc.).
    duration_sec : float
        Total duration of the audio in seconds (pre-computed by the caller
        via duration_of(); passed in to avoid re-reading the bytes).
    src_suffix : str
        Extension hint for the temp input file so ffmpeg detects the format
        correctly. Defaults to ".mp3" (the most common upload format).

    Returns
    -------
    list of (name, wav_bytes) — exactly 8 pairs, in Grid A then Grid B order:
        grid_a_sec_1, grid_a_sec_2, grid_a_sec_3, grid_a_sec_4,
        grid_b_sec_1, grid_b_sec_2, grid_b_sec_3, grid_b_sec_4

    All returned bytes are 16 kHz mono WAV suitable for whisper-cli.
    """
    dur = duration_sec
    sec_len = dur / 4.0          # Grid A section length
    half_sec = sec_len / 2.0     # Grid B offset = half a section

    # Grid A: 4 non-overlapping sections covering [0, dur]
    grid_a = [
        ("grid_a_sec_1", 0.0,         sec_len),
        ("grid_a_sec_2", sec_len,     2 * sec_len),
        ("grid_a_sec_3", 2 * sec_len, 3 * sec_len),
        ("grid_a_sec_4", 3 * sec_len, dur),
    ]

    # Grid B: 4 offset sections (offset by half a section_len), clamped to dur
    grid_b = [
        ("grid_b_sec_1", half_sec,         half_sec + sec_len),
        ("grid_b_sec_2", half_sec + sec_len,   half_sec + 2 * sec_len),
        ("grid_b_sec_3", half_sec + 2 * sec_len, half_sec + 3 * sec_len),
        ("grid_b_sec_4", half_sec + 3 * sec_len, dur),   # clamp last to dur
    ]

    pieces: list[tuple[str, bytes]] = []
    for name, start, end in grid_a + grid_b:
        end = min(end, dur)           # clamp (last Grid B may exceed dur)
        length = max(end - start, 0.0)
        wav_bytes = _extract_wav_section(audio_bytes, start, length, src_suffix)
        pieces.append((name, wav_bytes))

    return pieces
