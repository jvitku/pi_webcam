"""Thumbnail generation using Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def generate_thumbnail(
    source_path: Path,
    thumb_path: Path,
    width: int = 320,
    height: int = 180,
) -> bool:
    """Generate a thumbnail from a JPEG source image.

    Returns True on success, False on failure.
    """
    try:
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as img:
            img.thumbnail((width, height), Image.Resampling.LANCZOS)
            img.save(thumb_path, "JPEG", quality=80)
        return True
    except (OSError, ValueError):
        return False
