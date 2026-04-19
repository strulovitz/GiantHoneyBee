"""
video_cut.py — Temporal Grid A + Grid B video cut for GiantHoneyBee.

Produces exactly 8 (name, video_bytes, audio_bytes) tuples per cut.
Both the video chunk and the matching audio slice are returned together so
callers can upload them in a single upload_piece_with_audio() call.

Grid A — 4 non-overlapping time windows covering [0, duration]:
    grid_a_sec_1: [0,           dur/4)
    grid_a_sec_2: [dur/4,       dur/2)
    grid_a_sec_3: [dur/2,       3*dur/4)
    grid_a_sec_4: [3*dur/4,     dur)

Grid B — 4 offset windows (half a section_len offset), clamped to dur:
    grid_b_sec_1: [dur/8,         3*dur/8)
    grid_b_sec_2: [3*dur/8,       5*dur/8)
    grid_b_sec_3: [5*dur/8,       7*dur/8)
    grid_b_sec_4: [7*dur/8,       dur)

For each window:
  - video bytes: ffmpeg -ss START -t LEN re-encodes the clip to MP4
    (with audio track included so the MP4 is self-contained).
  - audio bytes: ffmpeg extracts the same window as 16 kHz mono WAV
    for downstream whisper processing.

MIN_VIDEO_CUT_SEC = 6.0 s — shorter than 2 × worker_clip_sec (2 × 3 s)
means children would be shorter than a Worker clip; no useful cut.

Plan reference: MULTIMEDIA_HIERARCHY_PLAN.md Sections 9, 11, 14e, 14f.
"""

import os
import subprocess
import tempfile
from pathlib import Path


# Minimum video duration to cut. Below this the tier passes through intact.
# 6 s = 2 × Worker clip length (3 s) — cutting shorter is pointless.
MIN_VIDEO_CUT_SEC = 6.0


def should_cut_video(duration_sec: float) -> bool:
    """Return True if this piece is long enough to be worth cutting into 8."""
    return duration_sec >= MIN_VIDEO_CUT_SEC


def _extract_video_chunk(
    src_path: str,
    start: float,
    length: float,
) -> bytes:
    """Extract [start, start+length) from src_path as MP4 bytes.

    Uses -ss before -i (fast seek) and re-encodes to ensure the output is
    a well-formed MP4 with correct timestamps. Audio is included (-c:a aac).
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f_out:
        dst_path = f_out.name
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{start:.6f}",
                "-i", src_path,
                "-t", f"{length:.6f}",
                "-c:v", "libx264",   # re-encode video for clean timestamps
                "-c:a", "aac",       # re-encode audio track
                "-movflags", "+faststart",
                dst_path,
            ],
            capture_output=True,
            check=True,
        )
        return Path(dst_path).read_bytes()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"_extract_video_chunk: ffmpeg failed for {src_path!r} "
            f"[{start:.2f}, {start + length:.2f}): "
            f"{e.stderr.decode(errors='replace')[:200]}"
        ) from e
    finally:
        try:
            os.unlink(dst_path)
        except OSError:
            pass


def _extract_audio_chunk(
    src_path: str,
    start: float,
    length: float,
) -> bytes:
    """Extract [start, start+length) from src_path as 16 kHz mono WAV bytes.

    Suitable for whisper-cli. Uses -vn to strip video, -ac 1 mono, -ar 16000.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_out:
        dst_path = f_out.name
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", f"{start:.6f}",
                "-i", src_path,
                "-t", f"{length:.6f}",
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                dst_path,
            ],
            capture_output=True,
            check=True,
        )
        return Path(dst_path).read_bytes()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"_extract_audio_chunk: ffmpeg failed for {src_path!r} "
            f"[{start:.2f}, {start + length:.2f}): "
            f"{e.stderr.decode(errors='replace')[:200]}"
        ) from e
    finally:
        try:
            os.unlink(dst_path)
        except OSError:
            pass


def cut_grid_ab_temporal_video(
    video_path: str,
    duration_sec: float,
) -> list[tuple[str, bytes, bytes]]:
    """Cut video_path into 8 Grid A + Grid B temporal windows.

    Parameters
    ----------
    video_path : str
        Path to the source video file.
    duration_sec : float
        Total duration in seconds (pre-computed by the caller via
        video_duration_of() to avoid redundant ffprobe calls).

    Returns
    -------
    list of (name, video_bytes, audio_bytes) — exactly 8 tuples:
        grid_a_sec_1, ..., grid_a_sec_4,
        grid_b_sec_1, ..., grid_b_sec_4

    video_bytes: MP4 with embedded audio.
    audio_bytes: 16 kHz mono WAV (suitable for whisper-cli).
    """
    dur = duration_sec
    sec_len = dur / 4.0
    half_sec = sec_len / 2.0  # Grid B offset

    # Grid A: 4 non-overlapping sections
    grid_a = [
        ("grid_a_sec_1", 0.0,             sec_len),
        ("grid_a_sec_2", sec_len,         2 * sec_len),
        ("grid_a_sec_3", 2 * sec_len,     3 * sec_len),
        ("grid_a_sec_4", 3 * sec_len,     dur),
    ]

    # Grid B: 4 offset sections, clamped to dur
    grid_b = [
        ("grid_b_sec_1", half_sec,                   half_sec + sec_len),
        ("grid_b_sec_2", half_sec + sec_len,         half_sec + 2 * sec_len),
        ("grid_b_sec_3", half_sec + 2 * sec_len,     half_sec + 3 * sec_len),
        ("grid_b_sec_4", half_sec + 3 * sec_len,     dur),
    ]

    pieces: list[tuple[str, bytes, bytes]] = []
    for name, start, end in grid_a + grid_b:
        end = min(end, dur)
        length = max(end - start, 0.0)
        if length < 0.1:
            # Degenerate window — produce minimal valid bytes
            # (should only happen if duration is very small)
            length = 0.1
        video_bytes = _extract_video_chunk(video_path, start, length)
        audio_bytes = _extract_audio_chunk(video_path, start, length)
        pieces.append((name, video_bytes, audio_bytes))

    return pieces
