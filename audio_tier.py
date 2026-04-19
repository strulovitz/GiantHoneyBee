"""
audio_tier.py — Shared audio-processing helper for all GiantHoneyBee tiers.

Used by raja_bee.py, giant_queen_client.py, dwarf_queen_client.py, and
worker_client.py. Each tier passes its own parameters; the function handles
downloading, gestalt (whisper-cli on 2× varispeed), cutting, child-component
creation, waiting, and text integration.

No shared-filesystem shortcuts — every piece crosses HTTP through the
KillerBee API as required by CLAUDE.md Rule #1 and the plan Section 10.

Timeout discipline (2026-04-19):
  - Whisper gestalt calls: per TIMEOUTS[audio_<tier>_gestalt] (plan Sec 14d).
  - Text integration: TIMEOUTS["text_integration"] = 120s.
  - Children poll loop: 1800s ceiling (waiting for 8 distributed machines;
    this is a poll loop, not an inference call).

Plan reference: MULTIMEDIA_HIERARCHY_PLAN.md Sections 6b, 9, 14d, 14f.
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
from audio_cut import (
    cut_grid_ab_temporal,
    duration_of,
    should_cut,
    MIN_SLICE_SEC,
)
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

_WHISPER_TIMEOUT = {
    "raja":        TIMEOUTS["audio_raja_gestalt"],   # 300s
    "giant_queen": TIMEOUTS["audio_gq_gestalt"],     # 180s
    "dwarf_queen": TIMEOUTS["audio_dq_gestalt"],     # 120s
    "worker":      TIMEOUTS["audio_worker_slice"],   # 60s
}

_TEXT_TIMEOUT = TIMEOUTS["text_integration"]  # 120s

# Whisper CLI binary
_WHISPER_BIN = Path.home() / "multimedia-feasibility" / "whisper.cpp" / "build" / "bin" / "whisper-cli"


# ── Whisper helpers ────────────────────────────────────────────────────────────

def _run_whisper(whisper_model_path: str, wav_path: str,
                 timeout_sec: float = 120.0) -> str:
    """Run whisper-cli on wav_path with -nt (no timestamps).

    Returns transcription text with leading/trailing whitespace stripped.
    Bracketed timestamps in the output (which -nt suppresses, but may appear
    from some builds) are also stripped.

    Returns the empty string on subprocess failure, timeout, or empty stdout.
    The caller decides whether to use a placeholder.
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
        print(f"  [AUDIO] whisper-cli timed out after {timeout_sec}s for {wav_path}")
        return ""
    except Exception as e:
        print(f"  [AUDIO] whisper-cli error: {e}")
        return ""


# ── Ollama text integration ────────────────────────────────────────────────────

def _needs_no_think(model: str) -> bool:
    """Return True if the model requires /no_think prefix (qwen3 family)."""
    return "qwen3" in model.lower()


def _run_ollama_text(model: str, prompt: str,
                     ollama_url: str = "http://localhost:11434",
                     timeout_sec: float = 120.0) -> str:
    """Run an Ollama text model and return the response string.

    Prepends /no_think for qwen3 family models. Falls back to thinking
    field if response is empty.
    """
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


# ── Cut-folder derivation (mirrors photo_tier._derive_cut_folder) ──────────────

def _derive_cut_folder(tier: str, job_id: int,
                       piece_url: Optional[str]) -> str:
    """Derive the cut folder path for this tier's children.

    For Raja:
        audio/swarmjob_<job_id>/cut_by_raja/

    For GiantQueen / DwarfQueen:
        <dir_of_piece_url>/cut_by_<tier_short>_<piece_stem>/
    """
    tier_short = _TIER_SHORT[tier]

    if tier == "raja":
        return f"audio/swarmjob_{job_id}/cut_by_raja/"

    piece_path = Path(piece_url.lstrip("/"))
    piece_stem = piece_path.stem       # e.g. "grid_a_sec_1"
    piece_dir = str(piece_path.parent) # e.g. "audio/swarmjob_42/cut_by_raja"
    return f"{piece_dir}/cut_by_{tier_short}_{piece_stem}/"


# ── Integration prompt ────────────────────────────────────────────────────────

def _build_integration_prompt(gestalt: str,
                               child_results: list[tuple[str, str]]) -> str:
    """Build the text-integration prompt from gestalt + 8 child results."""
    numbered = ""
    for i, (name, result_text) in enumerate(child_results, start=1):
        numbered += f"\n{i}. [{name}] {result_text}"

    return (
        f"My whisper transcription of this audio region "
        f"(2× varispeed, may be compressed): {gestalt}\n\n"
        f"My 8 sub-region transcriptions:{numbered}\n\n"
        "Write a coherent paragraph describing what is said or happening "
        "in this audio segment. Integrate the gestalt overview with the "
        "sub-region detail. Do not number or label sections. "
        "Output only the paragraph."
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def process_audio_piece(
    tier: str,
    component_id: Optional[int],
    job_id: int,
    piece_url: str,
    whisper_model_path: str,
    text_model: Optional[str],
    client: KillerBeeClient,
    ollama_url: str = "http://localhost:11434",
) -> str:
    """Process an audio piece at the given tier level.

    Downloads the piece via HTTP, runs whisper gestalt on a 2×-varispeed
    version, cuts into 8 children (non-leaf tiers), uploads children, waits
    for results, and integrates via a text model.

    Returns the paragraph this tier produces (caller submits to KillerBee).

    Parameters
    ----------
    tier : str
        One of "raja", "giant_queen", "dwarf_queen", "worker".
    component_id : int | None
        This tier's own component id. Raja passes None (operates on original).
    job_id : int
        The SwarmJob id.
    piece_url : str
        Server-relative path to this tier's piece, e.g.,
        "audio/swarmjob_42/cut_by_raja/grid_a_sec_1.wav" for GiantQueen.
        For Raja this is job.media_url, e.g.,
        "audio/swarmjob_42/original.mp3".
    whisper_model_path : str
        Absolute path to the ggml-*.bin whisper model for this tier.
    text_model : str | None
        Ollama model for integration (None for Worker leaf — STT IS the result).
    client : KillerBeeClient
        Authenticated KillerBeeClient instance.
    ollama_url : str
        Ollama API base URL.
    """
    if tier not in ("raja", "giant_queen", "dwarf_queen", "worker"):
        raise ValueError(f"process_audio_piece: unknown tier {tier!r}")

    whisper_timeout = _WHISPER_TIMEOUT[tier]

    # ── Step 1: Download the piece ────────────────────────────────────────────
    print(f"  [AUDIO/{tier.upper()}] Downloading piece: {piece_url}")
    raw_bytes = client.download_piece(piece_url)
    print(f"  [AUDIO/{tier.upper()}] Downloaded {len(raw_bytes)} bytes")

    # Determine the source file extension for temp file naming
    src_ext = Path(piece_url).suffix or ".mp3"  # e.g. ".mp3", ".wav"

    # Save to a temp file so we can run ffprobe/ffmpeg on it
    with tempfile.NamedTemporaryFile(suffix=src_ext, delete=False) as f_src:
        f_src.write(raw_bytes)
        src_path = f_src.name

    try:
        # ── Step 2: Compute duration ──────────────────────────────────────────
        dur = duration_of(src_path)
        print(f"  [AUDIO/{tier.upper()}] Duration: {dur:.2f}s")

        # ── Step 3: Gestalt — varispeed 2× then whisper ───────────────────────
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f_vs:
            varispeed_path = f_vs.name

        try:
            print(f"  [AUDIO/{tier.upper()}] Running 2× varispeed compression...")
            time_compress_audio(src_path, varispeed_path, ratio=2.0)

            print(f"  [AUDIO/{tier.upper()}] Running whisper gestalt "
                  f"(model={whisper_model_path}, timeout={whisper_timeout}s)...")
            gestalt = _run_whisper(whisper_model_path, varispeed_path,
                                   timeout_sec=whisper_timeout)
            if not gestalt:
                gestalt = "[audio gestalt returned empty]"
                print(f"  [AUDIO/{tier.upper()}] WARNING: whisper gestalt empty — "
                      f"using placeholder, continuing.")
            else:
                print(f"  [AUDIO/{tier.upper()}] Gestalt ({len(gestalt)} chars): "
                      f"{gestalt[:120]}...")
        finally:
            try:
                os.unlink(varispeed_path)
            except OSError:
                pass

        # ── Step 4: Leaf (Worker) — return gestalt directly ───────────────────
        if tier == "worker":
            return gestalt

        # ── Step 5: Pass-through for short pieces ─────────────────────────────
        if not should_cut(dur):
            print(f"  [AUDIO/{tier.upper()}] Piece too short ({dur:.2f}s < "
                  f"{MIN_SLICE_SEC}s) — pass-through, no cut.")
            return gestalt

        # ── Step 6: Non-leaf — cut, create children, upload, wait, integrate ──
        cut_folder = _derive_cut_folder(tier, job_id, piece_url)
        print(f"  [AUDIO/{tier.upper()}] Cut folder: {cut_folder}")

        child_level = _CHILD_LEVEL[tier]
        child_type = _CHILD_TYPE[tier]

        print(f"  [AUDIO/{tier.upper()}] Cutting audio into 8 Grid A+B sections "
              f"(dur={dur:.2f}s)...")
        pieces = cut_grid_ab_temporal(raw_bytes, dur, src_suffix=src_ext)
        print(f"  [AUDIO/{tier.upper()}] Got {len(pieces)} sections")

        child_ids = []
        piece_names = []
        for name, child_wav_bytes in pieces:
            child_piece_path = cut_folder + name + ".wav"

            child_id = client.create_child_component(
                parent_id=component_id,
                job_id=job_id,
                task_description=child_piece_path,
                level=child_level,
                piece_path=child_piece_path,
                component_type=child_type,
            )
            print(f"  [AUDIO/{tier.upper()}] Created child component {child_id} "
                  f"for {name} ({len(child_wav_bytes)} bytes)")

            client.upload_piece(child_id, child_piece_path, child_wav_bytes)
            print(f"  [AUDIO/{tier.upper()}] Uploaded {name} "
                  f"-> component {child_id}")

            child_ids.append(child_id)
            piece_names.append(name)

        # ── Step 7: Wait for children ──────────────────────────────────────────
        # Poll ceiling = 1800s: this waits for 8 separate machines over the
        # network. This is a poll loop, NOT an Ollama inference call.
        print(f"  [AUDIO/{tier.upper()}] Waiting for {len(child_ids)} children "
              f"(component_id={component_id}, poll ceiling=1800s)...")

        if component_id is None:
            # Raja case: no parent component id to poll by — poll each child
            # individually.
            timeout_sec = 1800
            poll_interval = 5
            waited = 0
            remaining = list(zip(piece_names, child_ids))
            child_results = []
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
                            result_text = (comp_resp.get("result")
                                           or "[audio gestalt returned empty]")
                            child_results.append((name, result_text))
                        else:
                            still_waiting.append((name, cid))
                    except Exception as e:
                        print(f"  [AUDIO/{tier.upper()}] Poll error child {cid}: {e}")
                        still_waiting.append((name, cid))
                remaining = still_waiting
                print(f"  [AUDIO/{tier.upper()}] {len(child_results)}/{len(child_ids)} "
                      f"children done ({waited}s)", end="\r")

            if remaining:
                raise TimeoutError(
                    f"process_audio_piece: Raja waited {timeout_sec}s, "
                    f"{len(remaining)} children still pending"
                )
        else:
            child_results = client.get_children_results(
                parent_component_id=component_id,
                timeout_sec=1800,
                poll_interval=5,
            )

        print(f"\n  [AUDIO/{tier.upper()}] All {len(child_results)} children done. "
              f"Running text integration with {text_model} "
              f"(timeout={_TEXT_TIMEOUT}s)...")

        # ── Step 8: Integrate ─────────────────────────────────────────────────
        integration_prompt = _build_integration_prompt(gestalt, child_results)
        paragraph = _run_ollama_text(text_model, integration_prompt,
                                     ollama_url, timeout_sec=_TEXT_TIMEOUT)
        print(f"  [AUDIO/{tier.upper()}] Integration paragraph "
              f"({len(paragraph)} chars): {paragraph[:120]}...")

        return paragraph

    finally:
        try:
            os.unlink(src_path)
        except OSError:
            pass
