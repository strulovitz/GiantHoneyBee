"""
photo_cut.py — Spatial Grid A + Grid B photo cut for GiantHoneyBee.

Ports the canonical cut geometry from HoneycombOfAI/queen_multimedia.py
(split_photo function). Does NOT import or depend on HoneycombOfAI code;
only PIL is required.

Grid A — 4 non-overlapping quadrants covering the full image:
    grid_a_q1 = upper-left   (0,0) -> (W/2, H/2)
    grid_a_q2 = upper-right  (W/2,0) -> (W, H/2)
    grid_a_q3 = lower-left   (0, H/2) -> (W/2, H)
    grid_a_q4 = lower-right  (W/2, H/2) -> (W, H)

Grid B — 4 offset quadrants straddling the Grid A boundaries, offset by
W/4 horizontally and H/4 vertically (same tile size as Grid A quadrants):
    grid_b_q1 = top-middle   (W/4, 0) -> (W-W/4, H/2)   — straddles A-q1/A-q2 boundary top
    grid_b_q2 = bottom-mid   (W/4, H/2) -> (W-W/4, H)   — straddles A-q3/A-q4 boundary bottom
    grid_b_q3 = left-middle  (0, H/4) -> (W/2, H-H/4)   — straddles A-q1/A-q3 boundary left
    grid_b_q4 = right-middle (W/2, H/4) -> (W, H-H/4)   — straddles A-q2/A-q4 boundary right

These names correspond to the queen_multimedia.py labels:
    A-UL = grid_a_q1, A-UR = grid_a_q2, A-LL = grid_a_q3, A-LR = grid_a_q4
    B-TOP-MID = grid_b_q1, B-BOT-MID = grid_b_q2,
    B-LEFT-MID = grid_b_q3, B-RIGHT-MID = grid_b_q4
"""

import io

from PIL import Image


def cut_grid_ab_spatial(pil_image: Image.Image) -> list[tuple[str, Image.Image]]:
    """Cut a PIL image into 8 Grid A + Grid B spatial pieces.

    Returns a list of 8 (name, sub_image) tuples in this order:
        grid_a_q1, grid_a_q2, grid_a_q3, grid_a_q4,
        grid_b_q1, grid_b_q2, grid_b_q3, grid_b_q4

    The image is converted to RGB before cutting so JPEG encoding works
    on every input (e.g., RGBA PNGs).
    """
    img = pil_image.convert("RGB")
    W, H = img.size
    qw, qh = W // 4, H // 4  # quarter dimensions for Grid B offset

    # Grid A: four non-overlapping quadrants
    grid_a_boxes = [
        ("grid_a_q1", (0,     0,     W // 2, H // 2)),   # upper-left
        ("grid_a_q2", (W // 2, 0,    W,      H // 2)),   # upper-right
        ("grid_a_q3", (0,     H // 2, W // 2, H)),        # lower-left
        ("grid_a_q4", (W // 2, H // 2, W,     H)),        # lower-right
    ]

    # Grid B: four offset quadrants (same tile size as Grid A quadrants)
    # Named to match queen_multimedia.py: B-TOP-MID, B-BOT-MID, B-LEFT-MID, B-RIGHT-MID
    grid_b_boxes = [
        ("grid_b_q1", (qw,     0,     W - qw, H // 2)),  # top-middle
        ("grid_b_q2", (qw,     H // 2, W - qw, H)),      # bottom-middle
        ("grid_b_q3", (0,      qh,    W // 2, H - qh)),  # left-middle
        ("grid_b_q4", (W // 2, qh,    W,      H - qh)),  # right-middle
    ]

    pieces = []
    for name, box in grid_a_boxes + grid_b_boxes:
        pieces.append((name, img.crop(box)))

    return pieces


def pil_to_jpeg_bytes(pil_image: Image.Image, quality: int = 90) -> bytes:
    """Encode a PIL image to JPEG bytes.

    Converts to RGB first so RGBA/palette images encode cleanly.
    """
    img = pil_image.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
