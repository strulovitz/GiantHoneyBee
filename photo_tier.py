"""
photo_tier.py — Shared photo-processing helper for all GiantHoneyBee tiers.

Used by raja_bee.py, giant_queen_client.py, dwarf_queen_client.py, and
worker_client.py. Each tier passes its own parameters; the function handles
downloading, gestalt, cutting, child-component creation, waiting, and
integration.

No shared-filesystem shortcuts — every piece crosses HTTP through the
KillerBee API as required by CLAUDE.md Rule #1 and the plan Section 10.

Timeout discipline (2026-04-19):
  All Ollama calls use tight per-call timeouts from tier_timeouts.TIMEOUTS.
  The wait_for_children poll loop uses 1800s (waiting for 8 distributed
  machines to finish is fundamentally different from a single inference
  call — that ceiling is NOT tightened here).
"""

import io
import os
import sys
from pathlib import Path
from typing import Optional

import ollama
from PIL import Image

from killerbee_client import KillerBeeClient
from photo_cut import cut_grid_ab_spatial, pil_to_jpeg_bytes

# tier_timeouts lives in HoneycombOfAI which is already on sys.path
# (every tier client inserts it). Import defensively.
try:
    from tier_timeouts import TIMEOUTS
except ImportError:
    # Fallback in case sys.path isn't set up yet
    _HONEYCOMB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'HoneycombOfAI')
    sys.path.insert(0, _HONEYCOMB)
    from tier_timeouts import TIMEOUTS


# ── Tier short-name map ────────────────────────────────────────────────────────

_TIER_SHORT = {
    "raja": "raja",
    "giant_queen": "gq",
    "dwarf_queen": "dq",
}

# ── Level map (what level do the CHILDREN get) ────────────────────────────────

_CHILD_LEVEL = {
    "raja": 0,        # Raja creates level-0 components for GiantQueens
    "giant_queen": 1, # GiantQueen creates level-1 components for DwarfQueens
    "dwarf_queen": 2, # DwarfQueen creates level-2 subtasks for Workers
}

# ── Component type for children ────────────────────────────────────────────────

_CHILD_TYPE = {
    "raja": "component",
    "giant_queen": "component",
    "dwarf_queen": "subtask",
}

# ── Vision timeout per tier (used in _run_ollama_vision) ──────────────────────

_VISION_TIMEOUT = {
    "raja":        TIMEOUTS["photo_raja_gestalt"],   # 300s
    "giant_queen": TIMEOUTS["photo_gq_gestalt"],     # 180s
    "dwarf_queen": TIMEOUTS["photo_dq_gestalt"],     # 120s
    "worker":      TIMEOUTS["photo_worker_tile"],    # 120s
}

# ── Text integration timeout (same for all non-leaf tiers) ────────────────────

_TEXT_TIMEOUT = TIMEOUTS["text_integration"]  # 120s


def _needs_no_think(model: str) -> bool:
    """Return True if this model requires the /no_think prefix.

    Per reference_empirical_model_limits.md and plan Section 8:
    qwen3-vl and qwen3.5 omnimodal families need /no_think.
    gemma3 and phi4-mini do not.
    """
    model_lower = model.lower()
    return "qwen3" in model_lower  # covers qwen3-vl, qwen3.5, qwen3:*


def _run_ollama_vision(model: str, image_bytes: bytes,
                       ollama_url: str = "http://localhost:11434",
                       timeout_sec: float = 120.0) -> str:
    """Run an Ollama vision model on image_bytes. Returns the description text.

    Prepends /no_think for qwen3 family models. Falls back to thinking field
    if response is empty (belt-and-suspenders per plan Section 8).
    num_predict >= 1024 per plan Section 8.

    timeout_sec is enforced at the httpx level — the connection is killed
    if inference exceeds the deadline.
    """
    # Fresh client per call with the correct timeout (httpx-backed)
    client = ollama.Client(host=ollama_url, timeout=timeout_sec)
    prompt = "/no_think Describe in detail what you see in this image." \
        if _needs_no_think(model) else \
        "Describe in detail what you see in this image."

    resp = client.generate(
        model=model,
        prompt=prompt,
        images=[image_bytes],
        options={
            "temperature": 0.1,
            "num_predict": 1024,
            "num_ctx": 8192,
        },
    )
    text = (resp.response or "").strip()
    if not text:
        thinking = getattr(resp, "thinking", "") or ""
        text = thinking.strip()
    return text


def _run_ollama_text(model: str, prompt: str,
                     ollama_url: str = "http://localhost:11434",
                     timeout_sec: float = 120.0) -> str:
    """Run an Ollama text model. Returns the response text.

    timeout_sec is enforced at the httpx level.
    """
    # Fresh client per call with the correct timeout (httpx-backed)
    client = ollama.Client(host=ollama_url, timeout=timeout_sec)
    # qwen3 text models also benefit from /no_think to avoid reasoning tokens
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


def _resize_image(img: Image.Image,
                  resize_spec: Optional[tuple[int, int]]) -> Image.Image:
    """Resize image to fit within (max_w, max_h) maintaining aspect ratio.

    If resize_spec is None, returns the image unchanged.
    """
    if resize_spec is None:
        return img
    max_w, max_h = resize_spec
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img


def _build_integration_prompt(gestalt: str,
                               child_results: list[tuple[str, str]]) -> str:
    """Build the text-model integration prompt from gestalt + child results."""
    numbered = ""
    for i, (name, result_text) in enumerate(child_results, start=1):
        numbered += f"\n{i}. [{name}] {result_text}"

    return (
        f"My gestalt of this region: {gestalt}\n\n"
        f"My 8 sub-region observers reported:{numbered}\n\n"
        "Write a single coherent paragraph describing the full region based on "
        "these observations. Integrate the sub-region detail with the overall "
        "gestalt. Do not number or label sections. Output only the paragraph."
    )


def _derive_cut_folder(tier: str, job_id: int,
                       piece_url: Optional[str],
                       component_id: Optional[int]) -> str:
    """Derive the cut folder path for this tier's children.

    For Raja (component_id is None / piece_url is the job's media_url):
        photo/swarmjob_<job_id>/cut_by_raja/

    For GiantQueen / DwarfQueen:
        <dir_of_piece_url>/cut_by_<tier_short>_<piece_stem>/

    The cut folder is a server-relative path under uploads/.
    """
    tier_short = _TIER_SHORT[tier]

    if tier == "raja":
        return f"photo/swarmjob_{job_id}/cut_by_raja/"

    # Non-raja: derive from piece_url
    piece_path = Path(piece_url.lstrip("/"))
    piece_stem = piece_path.stem          # e.g. "grid_a_q1"
    piece_dir = str(piece_path.parent)    # e.g. "photo/swarmjob_42/cut_by_raja"
    return f"{piece_dir}/cut_by_{tier_short}_{piece_stem}/"


def process_photo_piece(
    tier: str,
    component_id: Optional[int],
    job_id: int,
    piece_url: str,
    vision_model: str,
    text_model: Optional[str],
    resize_spec: Optional[tuple[int, int]],
    client: KillerBeeClient,
    ollama_url: str = "http://localhost:11434",
) -> str:
    """Process a photo piece at the given tier level.

    Downloads the piece via HTTP, runs gestalt vision, cuts into 8 children
    (non-leaf tiers), uploads children, waits for results, and integrates.

    Returns the paragraph this tier produces (caller submits to KillerBee).

    Parameters
    ----------
    tier : str
        One of "raja", "giant_queen", "dwarf_queen", "worker".
    component_id : int | None
        This tier's own component id. Raja passes None because Raja operates
        on the job's original file, not on a component.
    job_id : int
        The SwarmJob id.
    piece_url : str
        Server-relative path to this tier's piece (e.g.,
        "photo/swarmjob_42/cut_by_raja/grid_a_q1.jpg" for GiantQueen).
        For Raja, this is job.media_url (e.g., "photo/swarmjob_42/original.jpg").
    vision_model : str
        Ollama model for gestalt vision (e.g., "qwen3.5:9b").
    text_model : str | None
        Ollama model for integration (None for Worker leaf).
    resize_spec : tuple[int, int] | None
        (max_w, max_h) to resize before vision call. None = pass through.
    client : KillerBeeClient
        Authenticated KillerBeeClient instance.
    ollama_url : str
        Ollama API base URL.

    Timeout discipline:
        - Gestalt vision call: TIMEOUTS["photo_<tier>_gestalt"] seconds
          (300s for Raja, 180s for GQ, 120s for DQ/Worker).
        - Text integration call: TIMEOUTS["text_integration"] = 120s.
        - wait_for_children poll loop: 1800s ceiling (waiting for 8
          distributed machines; this is a poll loop, not an Ollama call,
          and is intentionally not tightened here).
    """
    if tier not in ("raja", "giant_queen", "dwarf_queen", "worker"):
        raise ValueError(f"Unknown tier: {tier!r}")

    vision_timeout = _VISION_TIMEOUT[tier]
    text_timeout = _TEXT_TIMEOUT

    print(f"  [PHOTO/{tier.upper()}] Downloading piece: {piece_url}")
    raw_bytes = client.download_piece(piece_url)
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    print(f"  [PHOTO/{tier.upper()}] Image size: {img.size}")

    # ── Gestalt: resize then vision ────────────────────────────────────────────
    gestalt_img = _resize_image(img.copy(), resize_spec)
    gestalt_bytes = pil_to_jpeg_bytes(gestalt_img)
    print(f"  [PHOTO/{tier.upper()}] Running gestalt vision with {vision_model} "
          f"(resized to {gestalt_img.size}, timeout={vision_timeout}s)...")
    gestalt = _run_ollama_vision(vision_model, gestalt_bytes, ollama_url,
                                 timeout_sec=vision_timeout)
    print(f"  [PHOTO/{tier.upper()}] Gestalt ({len(gestalt)} chars): {gestalt[:120]}...")

    # ── Leaf (Worker): return gestalt directly ─────────────────────────────────
    if tier == "worker":
        return gestalt

    # ── Non-leaf: cut into 8 pieces, create children, upload, wait, integrate ──

    cut_folder = _derive_cut_folder(tier, job_id, piece_url, component_id)
    print(f"  [PHOTO/{tier.upper()}] Cut folder: {cut_folder}")

    child_level = _CHILD_LEVEL[tier]
    child_type = _CHILD_TYPE[tier]

    print(f"  [PHOTO/{tier.upper()}] Cutting image into 8 Grid A+B pieces...")
    pieces = cut_grid_ab_spatial(img)  # cut the ORIGINAL (unresized) image

    child_ids = []
    for name, child_img in pieces:
        child_bytes = pil_to_jpeg_bytes(child_img)
        child_piece_path = cut_folder + name + ".jpg"

        # Create child component in KillerBee with piece_path pre-set
        child_id = client.create_child_component(
            parent_id=component_id,
            job_id=job_id,
            task_description=child_piece_path,  # task carries the path
            level=child_level,
            piece_path=child_piece_path,
            component_type=child_type,
        )
        print(f"  [PHOTO/{tier.upper()}] Created child component {child_id} "
              f"for {name} ({child_img.size})")

        # Upload the cut piece bytes
        client.upload_piece(child_id, child_piece_path, child_bytes)
        print(f"  [PHOTO/{tier.upper()}] Uploaded {name} ({len(child_bytes)} bytes) "
              f"-> component {child_id}")

        child_ids.append(child_id)

    # Wait for all 8 children to complete.
    # Poll ceiling = 1800s: this waits for 8 separate machines over the network.
    # This is a poll loop, NOT an Ollama inference call — intentionally not
    # tightened to the per-call Ollama timeouts.
    print(f"  [PHOTO/{tier.upper()}] Waiting for {len(child_ids)} children "
          f"(component_id={component_id}, poll ceiling=1800s)...")

    # get_children_results polls on parent_component_id
    # For Raja (component_id=None), we can't poll by parent_id=None directly.
    # Instead, poll each child individually and collect results.
    if component_id is None:
        # Raja case: poll each child component individually
        import time
        timeout_sec = 1800
        poll_interval = 5
        waited = 0
        remaining = list(zip([name for name, _ in pieces], child_ids))
        child_results = []
        while waited < timeout_sec and remaining:
            time.sleep(poll_interval)
            waited += poll_interval
            still_waiting = []
            for name, cid in remaining:
                try:
                    comp_resp = client._request("GET", f"/api/component/{cid}/status")
                    if comp_resp.get("status") == "completed" and comp_resp.get("result"):
                        child_results.append((name, comp_resp["result"]))
                    else:
                        still_waiting.append((name, cid))
                except Exception as e:
                    print(f"  [PHOTO/{tier.upper()}] Poll error for child {cid}: {e}")
                    still_waiting.append((name, cid))
            remaining = still_waiting
            print(f"  [PHOTO/{tier.upper()}] {len(child_results)}/{len(child_ids)} "
                  f"children done ({waited}s)", end="\r")
        if remaining:
            raise TimeoutError(
                f"process_photo_piece: Raja waited {timeout_sec}s, "
                f"{len(remaining)} children still pending"
            )
    else:
        child_results = client.get_children_results(
            parent_component_id=component_id,
            timeout_sec=1800,
            poll_interval=5,
        )

    print(f"\n  [PHOTO/{tier.upper()}] All {len(child_results)} children done. "
          f"Running text integration with {text_model} (timeout={text_timeout}s)...")

    integration_prompt = _build_integration_prompt(gestalt, child_results)
    paragraph = _run_ollama_text(text_model, integration_prompt, ollama_url,
                                 timeout_sec=text_timeout)
    print(f"  [PHOTO/{tier.upper()}] Integration paragraph "
          f"({len(paragraph)} chars): {paragraph[:120]}...")

    return paragraph
