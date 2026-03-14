"""Tests for thumbnail generation."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from pi_webcam.thumbnails import generate_thumbnail


class TestGenerateThumbnail:
    def test_basic_thumbnail(self, sample_jpeg: Path, tmp_path: Path) -> None:
        thumb_path = tmp_path / "thumb" / "test.jpg"
        result = generate_thumbnail(sample_jpeg, thumb_path, width=320, height=180)

        assert result is True
        assert thumb_path.exists()

        with Image.open(thumb_path) as img:
            assert img.width <= 320
            assert img.height <= 180

    def test_creates_parent_dirs(self, sample_jpeg: Path, tmp_path: Path) -> None:
        thumb_path = tmp_path / "a" / "b" / "c" / "thumb.jpg"
        result = generate_thumbnail(sample_jpeg, thumb_path)
        assert result is True
        assert thumb_path.exists()

    def test_missing_source(self, tmp_path: Path) -> None:
        result = generate_thumbnail(
            tmp_path / "nonexistent.jpg",
            tmp_path / "thumb.jpg",
        )
        assert result is False

    def test_corrupt_source(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "corrupt.jpg"
        bad_file.write_bytes(b"not a jpeg")
        result = generate_thumbnail(bad_file, tmp_path / "thumb.jpg")
        assert result is False

    def test_preserves_aspect_ratio(self, tmp_path: Path) -> None:
        # Create a wide image
        img = Image.new("RGB", (1920, 1080), color=(50, 100, 150))
        source = tmp_path / "wide.jpg"
        img.save(source, "JPEG")

        thumb_path = tmp_path / "thumb.jpg"
        generate_thumbnail(source, thumb_path, width=320, height=180)

        with Image.open(thumb_path) as result:
            assert result.width == 320
            assert result.height == 180

    def test_smaller_than_target(self, tmp_path: Path) -> None:
        # Create a small image
        img = Image.new("RGB", (100, 50), color=(50, 100, 150))
        source = tmp_path / "small.jpg"
        img.save(source, "JPEG")

        thumb_path = tmp_path / "thumb.jpg"
        generate_thumbnail(source, thumb_path, width=320, height=180)

        with Image.open(thumb_path) as result:
            # PIL thumbnail doesn't upscale
            assert result.width <= 100
            assert result.height <= 50
