"""
What a vision model sees in Cowork: a screenshot of the pinned window, annotated so the model can act on it.

- When UI Automation found elements, each one gets a numbered box whose number is its [id] ("Set-of-Marks"), so
  the model can match what it sees to click_element(id).
- When it found none (Electron, canvas, games, PDFs...), a coordinate grid labelled in screen pixels is drawn
  instead, so the model can read where to click_at(x, y).

The image is drawn in window pixels but every label is a screen coordinate, so it stays correct after the image is
scaled down for the model.
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

MAX_SIDE = 1280          # longest side sent to the model; bigger costs tokens without helping small models
GRID_STEP = 100          # screen pixels between grid lines
JPEG_QUALITY = 80

_BOX = (255, 59, 48)     # red: element boxes
_LABEL_TEXT = (255, 255, 255)
_GRID = (0, 160, 255)


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_marks(image: Image.Image, tagged: Dict[int, Dict[str, Any]], origin: Tuple[int, int]) -> Image.Image:
    """Draws each element's box and [id] label. origin is the window's top-left in screen coordinates."""
    img = image.convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _font(14)
    ox, oy = origin
    for tag_id, el in tagged.items():
        b = el.get("bounds") or {}
        x0, y0 = b.get("x", 0) - ox, b.get("y", 0) - oy
        x1, y1 = x0 + b.get("width", 0), y0 + b.get("height", 0)
        if x1 <= 0 or y1 <= 0 or x0 >= img.width or y0 >= img.height:
            continue  # outside the captured window
        draw.rectangle([x0, y0, x1, y1], outline=_BOX, width=2)
        label = str(tag_id)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        w, h = right - left + 6, bottom - top + 4
        # Label above the box, or just inside it when the box touches the top edge
        lx, ly = max(0, x0), (y0 - h if y0 - h >= 0 else max(0, y0))
        draw.rectangle([lx, ly, lx + w, ly + h], fill=_BOX)
        draw.text((lx + 3, ly + 1 - top), label, fill=_LABEL_TEXT, font=font)
    return img


def draw_grid(image: Image.Image, origin: Tuple[int, int], step: int = GRID_STEP) -> Image.Image:
    """Draws a light grid every `step` screen pixels, each line labelled with its screen coordinate."""
    img = image.convert("RGB")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(12)
    ox, oy = origin
    first_x = (-ox) % step  # the first window column that lands on a multiple of step in screen space
    for x in range(first_x, img.width, step):
        draw.line([(x, 0), (x, img.height)], fill=_GRID + (110,), width=1)
        draw.text((x + 2, 2), str(ox + x), fill=_GRID + (255,), font=font)
    first_y = (-oy) % step
    for y in range(first_y, img.height, step):
        draw.line([(0, y), (img.width, y)], fill=_GRID + (110,), width=1)
        draw.text((2, y + 2), str(oy + y), fill=_GRID + (255,), font=font)
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def encode_for_model(image: Image.Image, max_side: int = MAX_SIDE) -> str:
    """Base64 JPEG, scaled so its longest side is at most max_side."""
    img = image.convert("RGB")
    scale = min(1.0, max_side / max(img.width, img.height))
    if scale < 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def annotated_window_image(perceiver: Any, pin_manager: Any, hwnd: Optional[int],
                           tagged: Dict[int, Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """
    (base64 image, short note for the prompt) for the window, or None when it cannot be captured (no window,
    minimised, not Windows). Marks when elements were detected, a grid otherwise.
    """
    bounds = pin_manager.get_window_bounds(hwnd) if hwnd else None
    if not isinstance(bounds, dict) or bounds.get("width", 0) <= 0 or bounds.get("height", 0) <= 0:
        return None
    x, y, w, h = bounds["x"], bounds["y"], bounds["width"], bounds["height"]
    try:
        shot = perceiver.capture_screenshot(bbox=(x, y, x + w, y + h))
    except Exception:
        return None
    if not isinstance(shot, Image.Image):
        return None
    if tagged:
        image = draw_marks(shot, tagged, (x, y))
        note = ("A screenshot of the window is attached. Each red box is a detected element; its number is the [id] "
                "for click_element and type_into_element.")
    else:
        image = draw_grid(shot, (x, y))
        note = ("No UI elements could be read from this window, so a screenshot is attached with a blue grid "
                "labelled in screen pixels. Find the target in the image and use click_at(x, y) with screen "
                "coordinates read from the grid labels.")
    return encode_for_model(image), note


async def vision_enabled(mode: str, model_id: str, ollama_mgr: Any) -> bool:
    """
    Whether Cowork sends screenshots to this model. mode is the config's cowork.vision: "never", "local" (only
    local Ollama models that report the vision capability) or "always" (cloud models too).
    """
    mode = (mode or "local").lower()
    if mode == "never":
        return False
    if model_id.startswith("ollama/") or "/" not in model_id:
        return "vision" in await ollama_mgr.capabilities(model_id)
    return mode == "always"
