"""Best-effort thumbnail generation for uploaded items.

Writes ~256x256 JPEGs to ~/brain/items/thumbs/{item_id}.jpg. Used by the Files
browser list view; never blocks an ingest, since a missing thumbnail just
falls back to a kind icon in the UI.
"""

from __future__ import annotations

import logging
import uuid
from io import BytesIO
from pathlib import Path

from m3.brain.layout import BrainPaths

logger = logging.getLogger("m3.thumbnails")

THUMB_MAX = 256
THUMB_QUALITY = 80

_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"}


def thumbs_dir(brain_root: Path) -> Path:
    return BrainPaths(brain_root).root / "items" / "thumbs"


def thumb_path(brain_root: Path, item_id: uuid.UUID | str) -> Path:
    return thumbs_dir(brain_root) / f"{item_id}.jpg"


def generate_thumbnail(
    brain_root: Path,
    item_id: uuid.UUID | str,
    *,
    original_path: Path | None,
    content_kind: str,
) -> Path | None:
    """Try to create a thumbnail for the item. Returns the path on success, None otherwise.

    Failures are logged at warning level but never raised — thumbnailing is
    cosmetic and must not break ingest.
    """
    if original_path is None or not original_path.exists():
        return None
    try:
        out_dir = thumbs_dir(brain_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = thumb_path(brain_root, item_id)
        ext = original_path.suffix.lstrip(".").lower()
        if content_kind == "image" or ext in _IMAGE_EXTS:
            return _thumb_image(original_path, target)
        if content_kind == "pdf" or ext == "pdf":
            return _thumb_pdf(original_path, target)
        return None
    except Exception as e:
        logger.warning("thumbnail generation failed for %s: %s", item_id, e)
        return None


def _thumb_image(src: Path, target: Path) -> Path | None:
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed; skipping image thumbnail")
        return None
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_MAX, THUMB_MAX))
        im.save(target, "JPEG", quality=THUMB_QUALITY, optimize=True)
    return target


def _thumb_pdf(src: Path, target: Path) -> Path | None:
    try:
        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError:
        logger.warning("pypdfium2 / Pillow not installed; skipping PDF thumbnail")
        return None
    pdf = pdfium.PdfDocument(src)
    try:
        if len(pdf) == 0:
            return None
        page = pdf[0]
        # scale=1 → 72dpi. scale=2 produces a crisp 256-wide thumbnail for
        # most letter-size pages without rendering at native resolution.
        bitmap = page.render(scale=2)
        pil = bitmap.to_pil().convert("RGB")
        pil.thumbnail((THUMB_MAX, THUMB_MAX))
        pil.save(target, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return target
    finally:
        pdf.close()
