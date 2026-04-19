"""
frame_sample.py — ffmpeg-based frame sampling and duration probe for video.

Ported from HoneycombOfAI/queen_multimedia.py (extract_frames, probe_duration)
and adapted for the GiantHoneyBee multi-tier video pipeline.

Functions
---------
video_duration_of(video_path) -> float
    Return video duration in seconds via ffprobe.

sample_frames_at_fps(video_path, target_fps, max_frames=60) -> list[bytes]
    Extract JPEG frames at target_fps from the whole video (or clip).
    Returns a list of JPEG byte strings, capped at max_frames (the
    empirical qwen3-vl ceiling from reference_empirical_model_limits.md).
    Uses a tempdir so no stdout-pipe parsing is needed.

Plan reference: MULTIMEDIA_HIERARCHY_PLAN.md Sections 9, 14f.
Empirical limits: reference_empirical_model_limits.md — qwen3-vl tested to
60 frames; /no_think required. Never exceed 60 frames per call.
"""

import os
import subprocess
import tempfile
from pathlib import Path


def video_duration_of(video_path: str) -> float:
    """Return the duration of a video file in seconds via ffprobe.

    Raises RuntimeError if ffprobe cannot parse the duration.
    """
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            video_path,
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
        f"video_duration_of: could not parse duration from ffprobe for "
        f"{video_path!r}. stdout={r.stdout!r} stderr={r.stderr!r}"
    )


def sample_frames_at_fps(
    video_path: str,
    target_fps: float,
    max_frames: int = 60,
) -> list[bytes]:
    """Extract JPEG frames from video_path at target_fps, up to max_frames.

    Parameters
    ----------
    video_path : str
        Path to the source video file (.mp4 etc.).
    target_fps : float
        Frames per second to extract (e.g. 1.0 for parent gestalt,
        2.0 for Worker clips per plan Section 9).
    max_frames : int
        Hard cap on frame count. Default 60 (qwen3-vl empirical ceiling).

    Returns
    -------
    list[bytes]
        JPEG bytes for each extracted frame, in time order.
        Empty list if ffmpeg fails or no frames are produced.

    Implementation: tempdir approach (simpler and more robust than piping
    concatenated MJPEG via stdout). ffmpeg writes frame_%04d.jpg files
    which are read back and returned.
    """
    if target_fps <= 0:
        raise ValueError(f"sample_frames_at_fps: target_fps must be > 0, got {target_fps}")

    with tempfile.TemporaryDirectory() as td:
        frame_pattern = os.path.join(td, "frame_%04d.jpg")

        # vf=fps=<target_fps> subsamples the video stream at the requested rate.
        # -frames:v <max_frames> truncates extraction once we have enough.
        # -q:v 2 gives near-lossless JPEG quality (1=best, 31=worst).
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-vf", f"fps={target_fps}",
                    "-frames:v", str(max_frames),
                    "-q:v", "2",
                    frame_pattern,
                ],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"  [frame_sample] ffmpeg error extracting frames: "
                  f"{e.stderr.decode(errors='replace')[:200]}")
            return []

        # Collect sorted frame files
        frame_paths = sorted(Path(td).glob("frame_*.jpg"))
        frames = [fp.read_bytes() for fp in frame_paths[:max_frames]]

    return frames
