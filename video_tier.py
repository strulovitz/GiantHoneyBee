"""
video_tier.py — Shared video-processing helper for all GiantHoneyBee tiers.

Used by raja_bee.py, giant_queen_client.py, dwarf_queen_client.py, and
worker_client.py. Each tier passes its own parameters; the function handles
downloading, visual gestalt (qwen3-vl on low-FPS frames), audio gestalt
(whisper on 2× varispeed audio), cutting, child creation, waiting, and
text integration.

Slippery Point 7 compliance:
  Workers receive VIDEO CLIPS (short time windows of the full frame), NOT
  single frames. The vision model (qwen3-vl:8b) is fed MULTIPLE frames from
  the clip so it can perceive motion — exactly as prescribed by Chapter 15.
  At the Worker tier the clip is already short (produced by the parent's cut),
  and frames are sampled at 2 FPS (≈6 frames for a 3-second Worker clip).
  A log line records frame count so the Slippery-Point compliance can be
  verified after a run.

No shared-filesystem shortcuts — every piece crosses HTTP through the
KillerBee API as required by CLAUDE.md Rule #1 and the plan Section 10.

Timeout discipline (2026-04-19):
  - Visual gestalt (Ollama/qwen3-vl): per TIMEOUTS["video_<tier>_gestalt"].
  - Audio gestalt (whisper-cli):       per TIMEOUTS["video_<tier>_gestalt"].
  - Text integration:                  TIMEOUTS["text_integration"] = 120s.
  - Children poll loop:                1800s ceiling (waiting for 8 distributed
    machines; this is a poll loop, not an inference call).

Plan reference: MULTIMEDIA_HIERARCHY_PLAN.md Sections 6c, 9, 11, 14e.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import ollama

from killerbee_client import KillerBeeClient
from frame_sample import sample_frames_at_fps, video_duration_of
from video_cut import cut_grid_ab_temporal_video, should_cut_video, MIN_VIDEO_CUT_SEC
from varispeed import time_compress_audio

# tier_timeouts lives in HoneycombOfAI which is already on sys.path
# (every tier client inserts it). Import defensively.
try:
    from tier_timeouts import TIMEOUTS
except ImportError:
    _HONEYCOMB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'HoneycombOfAI')
    sys.path.insert(0, _HONEYCOMB)
    from tier_timeouts import TIMEOUTS


# ── Tier configuration maps ────────────────────────────────────────────────────

_TIER_SHORT = {
    "raja":        "raja",
    "giant_queen": "gq",
    "dwarf_queen": "dq",
}

_CHILD_LEVEL = {
    "raja":        0,   # creates level-0 components for GiantQueens
    "giant_queen": 1,   # creates level-1 components for DwarfQueens
    "dwarf_queen": 2,   # creates level-2 subtasks for Workers
}

_CHILD_TYPE = {
    "raja":        "component",
    "giant_queen": "component",
    "dwarf_queen": "subtask",
}

# Frame sampling rates per tier per plan Section 9
# Parent tiers: 1 FPS (low-fidelity gestalt of the full region)
# Worker tier:  2 FPS (motion-perceiving clip — Slippery Point 7)
_GESTALT_FPS = {
    "raja":        1.0,
    "giant_queen": 1.0,
    "dwarf_queen": 1.0,
    "worker":      2.0,   # Worker sees clips at 2 FPS per plan Section 9
}

_VISUAL_TIMEOUT = {
    "raja":        TIMEOUTS["video_raja_gestalt"],   # 300s
    "giant_queen": TIMEOUTS["video_gq_gestalt"],     # 300s
    "dwarf_queen": TIMEOUTS["video_dq_gestalt"],     # 180s
    "worker":      TIMEOUTS["video_worker_clip"],    # 180s
}

_WHISPER_TIMEOUT = {
    "raja":        TIMEOUTS["video_raja_gestalt"],   # 300s
    "giant_queen": TIMEOUTS["video_gq_gestalt"],     # 300s
    "dwarf_queen": TIMEOUTS["video_dq_gestalt"],     # 180s
    "worker":      TIMEOUTS["video_worker_clip"],    # 180s
}

_TEXT_TIMEOUT = TIMEOUTS["text_integration"]   # 120s

# Whisper CLI binary (same path used in audio_tier.py)
_WHISPER_BIN = (
    Path.home() / "multimedia-feasibility" / "whisper.cpp" / "build" / "bin" / "whisper-cli"
)


# ── Whisper helper (identical to audio_tier._run_whisper) ─────────────────────

def _run_whisper(whisper_model_path: str, wav_path: str,
                 timeout_sec: float = 120.0) -> str:
    """Run whisper-cli on wav_path with -nt (no timestamps).

    Returns stripped transcription text or empty string on failure.
    """
    try:
        r = subprocess.run(
            [str(_WHISPER_BIN), "-m", whisper_model_path, "-f", wav_path, "-nt"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        text = r.stdout.strip()
        # Strip bracketed timestamps such as [00:00:00.000 --> 00:00:05.000]
        text = re.sub(r"\[\d+:\d+:\d+\.\d+\s*-->\s*\d+:\d+:\d+\.\d+\]", "", text)
        return text.strip()
    except subprocess.TimeoutExpired:
        print(f"  [VIDEO] whisper-cli timed out after {timeout_sec}s for {wav_path}")
        return ""
    except Exception as e:
        print(f"  [VIDEO] whisper-cli error: {e}")
        return ""


# ── Ollama vision helper ───────────────────────────────────────────────────────

def _run_ollama_vision(model: str, frame_bytes_list: list[bytes],
                       ollama_url: str = "http://localhost:11434",
                       timeout_sec: float = 180.0) -> str:
    """Run qwen3-vl on a list of JPEG frames.

    Always prepends /no_think (all video tiers use qwen3-vl which requires
    it per plan Section 8 and reference_empirical_model_limits.md).
    Falls back to thinking field if response is empty.
    """
    client = ollama.Client(host=ollama_url, timeout=timeout_sec)
    prompt = (
        "/no_think Describe what is happening in this video. "
        "Pay attention to motion, actions, and visual changes across the frames."
    )
    resp = client.generate(
        model=model,
        prompt=prompt,
        images=frame_bytes_list,
        options={
            "temperature": 0.1,
            "num_predict": 1024,
            "num_ctx": 32768,   # large ctx for multi-frame visual tokens
        },
    )
    text = (resp.response or "").strip()
    if not text:
        thinking = getattr(resp, "thinking", "") or ""
        text = thinking.strip()
    return text


# ── Ollama text integration helper ────────────────────────────────────────────

def _needs_no_think(model: str) -> bool:
    return "qwen3" in model.lower()


def _run_ollama_text(model: str, prompt: str,
                     ollama_url: str = "http://localhost:11434",
                     timeout_sec: float = 120.0) -> str:
    """Run an Ollama text model and return the response string."""
    client = ollama.Client(host=ollama_url, timeout=timeout_sec)
    if _needs_no_think(model):
        prompt = "/no_think " + prompt
    resp = client.generate(
        model=model,
        prompt=prompt,
        options={
            "temperature": 0.3,
            "num_predict": 2048,
            "num_ctx": 8192,
        },
    )
    text = (resp.response or "").strip()
    if not text:
        thinking = getattr(resp, "thinking", "") or ""
        text = thinking.strip()
    return text


# ── Cut folder derivation (mirrors audio_tier._derive_cut_folder) ─────────────

def _derive_cut_folder(tier: str, job_id: int,
                       video_url: Optional[str]) -> str:
    """Derive the cut folder path for this tier's children.

    For Raja:
        video/swarmjob_<job_id>/cut_by_raja/

    For GiantQueen / DwarfQueen:
        <dir_of_video_url>/cut_by_<tier_short>_<piece_stem>/
    """
    tier_short = _TIER_SHORT[tier]

    if tier == "raja":
        return f"video/swarmjob_{job_id}/cut_by_raja/"

    piece_path = Path(video_url.lstrip("/"))
    piece_stem = piece_path.stem        # e.g. "grid_a_sec_1"
    piece_dir = str(piece_path.parent)  # e.g. "video/swarmjob_42/cut_by_raja"
    return f"{piece_dir}/cut_by_{tier_short}_{piece_stem}/"


# ── Integration prompt ────────────────────────────────────────────────────────

def _build_integration_prompt(
    visual_gestalt: str,
    audio_gestalt: str,
    child_results: list[tuple[str, str]],
) -> str:
    """Build the text-model integration prompt for non-leaf tiers."""
    numbered = ""
    for i, (name, result_text) in enumerate(child_results, start=1):
        numbered += f"\n{i}. [{name}] {result_text}"

    return (
        f"My visual observation (from sampling frames at 1 FPS across this "
        f"video segment): {visual_gestalt}\n\n"
        f"My audio observation (from whisper on 2× varispeed audio track): "
        f"{audio_gestalt}\n\n"
        f"My 8 sub-region children reported:{numbered}\n\n"
        "Write one coherent paragraph describing what happens in this video "
        "segment — motion, actions, dialogue, atmosphere. Integrate all "
        "observations. Do not number or label sections. Output only the paragraph."
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def process_video_piece(
    tier: str,
    component_id: Optional[int],
    job_id: int,
    video_url: str,
    audio_url: Optional[str],
    vision_model: str,
    whisper_model_path: str,
    text_model: Optional[str],
    client: KillerBeeClient,
    ollama_url: str = "http://localhost:11434",
) -> str:
    """Process a video piece at the given tier level.

    Downloads the video (and audio slice, if provided) via HTTP, runs the
    visual gestalt (qwen3-vl on low-FPS frames) and audio gestalt (whisper
    on 2× varispeed), cuts into 8 children (non-leaf tiers), uploads
    children, waits for results, and integrates.

    Returns the paragraph this tier produces (caller submits to KillerBee).

    Parameters
    ----------
    tier : str
        One of "raja", "giant_queen", "dwarf_queen", "worker".
    component_id : int | None
        This tier's own component id. Raja passes None (operates on original).
    job_id : int
        The SwarmJob id.
    video_url : str
        Server-relative path to the video piece, e.g.
        "video/swarmjob_42/original.mp4" for Raja.
    audio_url : str | None
        Server-relative path to the matching audio slice, e.g.
        "video/swarmjob_42/original_audio.mp3".
        If None, the audio track is extracted from the video via ffmpeg.
    vision_model : str
        Ollama model for visual gestalt (always "qwen3-vl:8b" per plan 6c).
    whisper_model_path : str
        Absolute path to the ggml-*.bin whisper model for this tier.
    text_model : str | None
        Ollama model for integration. None for Worker (leaf; no integration).
    client : KillerBeeClient
        Authenticated KillerBeeClient instance.
    ollama_url : str
        Ollama API base URL.
    """
    if tier not in ("raja", "giant_queen", "dwarf_queen", "worker"):
        raise ValueError(f"process_video_piece: unknown tier {tier!r}")

    visual_timeout = _VISUAL_TIMEOUT[tier]
    whisper_timeout = _WHISPER_TIMEOUT[tier]
    gestalt_fps = _GESTALT_FPS[tier]

    # ── Step 1: Download video ────────────────────────────────────────────────
    print(f"  [VIDEO/{tier.upper()}] Downloading video: {video_url}")
    video_bytes = client.download_piece(video_url)
    print(f"  [VIDEO/{tier.upper()}] Downloaded {len(video_bytes)} bytes")

    # Save to temp .mp4 so ffprobe / ffmpeg can operate on it
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f_vid:
        f_vid.write(video_bytes)
        video_tmp = f_vid.name

    try:
        # ── Step 2: Compute duration ──────────────────────────────────────────
        dur = video_duration_of(video_tmp)
        print(f"  [VIDEO/{tier.upper()}] Duration: {dur:.2f}s")

        # ── Step 3: Download or extract audio ─────────────────────────────────
        if audio_url:
            print(f"  [VIDEO/{tier.upper()}] Downloading audio: {audio_url}")
            audio_bytes = client.download_piece(audio_url)
            print(f"  [VIDEO/{tier.upper()}] Audio downloaded: {len(audio_bytes)} bytes")
            with tempfile.NamedTemporaryFile(
                suffix=Path(audio_url).suffix or ".mp3", delete=False
            ) as f_aud:
                f_aud.write(audio_bytes)
                audio_tmp = f_aud.name
        else:
            # Extract audio from the video (Raja's case for the original file
            # when audio_url is None — should not normally happen since the
            # submit route extracts original_audio.mp3, but kept as a fallback).
            print(f"  [VIDEO/{tier.upper()}] audio_url not provided — extracting from video")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_aud:
                audio_tmp = f_aud.name
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_tmp,
                    "-vn", "-ac", "1", "-ar", "16000",
                    audio_tmp,
                ],
                capture_output=True,
                check=True,
            )
            print(f"  [VIDEO/{tier.upper()}] Audio extracted to temp WAV")

        try:
            # ── Step 4: Visual gestalt ────────────────────────────────────────
            print(f"  [VIDEO/{tier.upper()}] Sampling frames at {gestalt_fps} FPS "
                  f"(max=60)...")
            frames = sample_frames_at_fps(video_tmp, gestalt_fps, max_frames=60)
            n_frames = len(frames)
            print(f"  [VIDEO/{tier.upper()}] Extracted {n_frames} frames "
                  f"[SLIPPERY_POINT_7_CHECK: n_frames={n_frames}]")

            if frames:
                print(f"  [VIDEO/{tier.upper()}] Running visual gestalt with "
                      f"{vision_model} ({n_frames} frames, "
                      f"timeout={visual_timeout}s)...")
                visual_gestalt = _run_ollama_vision(
                    vision_model, frames, ollama_url, timeout_sec=visual_timeout
                )
                if not visual_gestalt:
                    visual_gestalt = "[video visual gestalt empty]"
                    print(f"  [VIDEO/{tier.upper()}] WARNING: visual gestalt empty — "
                          f"using placeholder, continuing.")
                else:
                    print(f"  [VIDEO/{tier.upper()}] Visual gestalt "
                          f"({len(visual_gestalt)} chars): {visual_gestalt[:120]}...")
            else:
                visual_gestalt = "[video visual gestalt empty — no frames extracted]"
                print(f"  [VIDEO/{tier.upper()}] WARNING: no frames extracted — "
                      f"using placeholder.")

            # ── Step 5: Audio gestalt ─────────────────────────────────────────
            print(f"  [VIDEO/{tier.upper()}] Running 2× varispeed on audio track...")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_vs:
                varispeed_tmp = f_vs.name
            try:
                time_compress_audio(audio_tmp, varispeed_tmp, ratio=2.0)
                print(f"  [VIDEO/{tier.upper()}] Running whisper gestalt "
                      f"(timeout={whisper_timeout}s)...")
                audio_gestalt = _run_whisper(
                    whisper_model_path, varispeed_tmp, timeout_sec=whisper_timeout
                )
                if not audio_gestalt:
                    audio_gestalt = "[video audio gestalt empty]"
                    print(f"  [VIDEO/{tier.upper()}] WARNING: audio gestalt empty — "
                          f"using placeholder, continuing.")
                else:
                    print(f"  [VIDEO/{tier.upper()}] Audio gestalt "
                          f"({len(audio_gestalt)} chars): {audio_gestalt[:120]}...")
            finally:
                try:
                    os.unlink(varispeed_tmp)
                except OSError:
                    pass

            # ── Step 6: Worker leaf — combine and return ───────────────────────
            if tier == "worker":
                worker_text = (
                    f"VISUAL: {visual_gestalt}\n"
                    f"AUDIO: {audio_gestalt}"
                )
                print(f"  [VIDEO/{tier.upper()}] Worker leaf result "
                      f"({len(worker_text)} chars)")
                return worker_text

            # ── Step 7: Pass-through for short pieces ──────────────────────────
            if not should_cut_video(dur):
                print(f"  [VIDEO/{tier.upper()}] Piece too short ({dur:.2f}s < "
                      f"{MIN_VIDEO_CUT_SEC}s) — pass-through, no cut.")
                # Return simple combined gestalt; no children
                pass_text = (
                    f"VISUAL: {visual_gestalt}\n"
                    f"AUDIO: {audio_gestalt}"
                )
                return pass_text

            # ── Step 8: Non-leaf — cut, create children, upload, wait, integrate
            cut_folder = _derive_cut_folder(tier, job_id, video_url)
            print(f"  [VIDEO/{tier.upper()}] Cut folder: {cut_folder}")

            child_level = _CHILD_LEVEL[tier]
            child_type = _CHILD_TYPE[tier]

            print(f"  [VIDEO/{tier.upper()}] Cutting video into 8 Grid A+B sections "
                  f"(dur={dur:.2f}s)...")
            pieces = cut_grid_ab_temporal_video(video_tmp, dur)
            print(f"  [VIDEO/{tier.upper()}] Got {len(pieces)} sections")

            child_ids = []
            piece_names = []
            for name, child_video_bytes, child_audio_bytes in pieces:
                child_video_path = cut_folder + name + ".mp4"
                child_audio_path = cut_folder + name + "_audio.wav"

                child_id = client.create_child_component(
                    parent_id=component_id,
                    job_id=job_id,
                    task_description=child_video_path,
                    level=child_level,
                    piece_path=child_video_path,
                    component_type=child_type,
                )
                print(f"  [VIDEO/{tier.upper()}] Created child component {child_id} "
                      f"for {name} (video={len(child_video_bytes)}B "
                      f"audio={len(child_audio_bytes)}B)")

                client.upload_piece_with_audio(
                    child_id,
                    child_video_path,
                    child_video_bytes,
                    child_audio_path,
                    child_audio_bytes,
                )
                print(f"  [VIDEO/{tier.upper()}] Uploaded {name} "
                      f"-> component {child_id}")

                child_ids.append(child_id)
                piece_names.append(name)

            # ── Step 9: Wait for children ──────────────────────────────────────
            print(f"  [VIDEO/{tier.upper()}] Waiting for {len(child_ids)} children "
                  f"(component_id={component_id}, poll ceiling=1800s)...")

            if component_id is None:
                # Raja case: no parent component id — poll each child individually.
                timeout_sec = 1800
                poll_interval = 5
                waited = 0
                remaining = list(zip(piece_names, child_ids))
                child_results: list[tuple[str, str]] = []
                while waited < timeout_sec and remaining:
                    time.sleep(poll_interval)
                    waited += poll_interval
                    still_waiting = []
                    for name, cid in remaining:
                        try:
                            comp_resp = client._request(
                                "GET", f"/api/component/{cid}/status"
                            )
                            if comp_resp.get("status") == "completed":
                                result_text = (
                                    comp_resp.get("result")
                                    or "[video gestalt returned empty]"
                                )
                                child_results.append((name, result_text))
                            else:
                                still_waiting.append((name, cid))
                        except Exception as e:
                            print(f"  [VIDEO/{tier.upper()}] Poll error child "
                                  f"{cid}: {e}")
                            still_waiting.append((name, cid))
                    remaining = still_waiting
                    print(f"  [VIDEO/{tier.upper()}] {len(child_results)}/{len(child_ids)} "
                          f"children done ({waited}s)", end="\r")

                if remaining:
                    raise TimeoutError(
                        f"process_video_piece: Raja waited {timeout_sec}s, "
                        f"{len(remaining)} children still pending"
                    )
            else:
                child_results = client.get_children_results(
                    parent_component_id=component_id,
                    timeout_sec=1800,
                    poll_interval=5,
                )

            print(f"\n  [VIDEO/{tier.upper()}] All {len(child_results)} children done. "
                  f"Running text integration with {text_model} "
                  f"(timeout={_TEXT_TIMEOUT}s)...")

            # ── Step 10: Integrate ─────────────────────────────────────────────
            integration_prompt = _build_integration_prompt(
                visual_gestalt, audio_gestalt, child_results
            )
            paragraph = _run_ollama_text(
                text_model, integration_prompt, ollama_url,
                timeout_sec=_TEXT_TIMEOUT
            )
            print(f"  [VIDEO/{tier.upper()}] Integration paragraph "
                  f"({len(paragraph)} chars): {paragraph[:120]}...")

            return paragraph

        finally:
            try:
                os.unlink(audio_tmp)
            except OSError:
                pass

    finally:
        try:
            os.unlink(video_tmp)
        except OSError:
            pass
