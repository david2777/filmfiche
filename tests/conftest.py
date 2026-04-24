"""
Shared pytest fixtures that build a temporary directory of synthetic test images.

Scenarios covered
-----------------
full_exif      – JPEG with DateTimeOriginal + Make + Model
date_only      – JPEG with DateTimeOriginal but no camera tags
no_exif        – JPEG with no EXIF at all
wrong_date_fmt – JPEG with a malformed date string
png_no_exif    – PNG (no EXIF support in most encoders) — tests extension handling
"""

import struct
from datetime import datetime
from pathlib import Path

import piexif
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _base_exif() -> dict:
    """Return a minimal piexif structure with empty sub-dicts."""
    return {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}


def _make_jpeg(path: Path, exif_dict: dict | None) -> Path:
    """Save a 1×1 RGB JPEG to *path*, optionally embedding *exif_dict*."""
    img = Image.new("RGB", (1, 1), color=(100, 149, 237))
    kwargs = {}
    if exif_dict is not None:
        kwargs["exif"] = piexif.dump(exif_dict)
    img.save(path, format="JPEG", **kwargs)
    return path


def _make_png(path: Path) -> Path:
    """Save a 1×1 RGB PNG (no EXIF) to *path*."""
    img = Image.new("RGB", (1, 1), color=(255, 165, 0))
    img.save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# Individual file fixtures  (each writes to pytest's tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture()
def jpeg_full_exif(tmp_path) -> Path:
    """JPEG with DateTimeOriginal, Make, and Model."""
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2023:06:15 10:30:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Canon"
    exif["0th"][piexif.ImageIFD.Model] = b"EOS R5"
    return _make_jpeg(tmp_path / "full_exif.jpg", exif)


@pytest.fixture()
def jpeg_date_only(tmp_path) -> Path:
    """JPEG with DateTimeOriginal but no camera tags."""
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2021:12:01 08:00:00"
    return _make_jpeg(tmp_path / "date_only.jpg", exif)


@pytest.fixture()
def jpeg_no_exif(tmp_path) -> Path:
    """JPEG with no EXIF data at all."""
    return _make_jpeg(tmp_path / "no_exif.jpg", None)


@pytest.fixture()
def jpeg_wrong_date_fmt(tmp_path) -> Path:
    """JPEG with a malformed date string."""
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"not-a-date"
    exif["0th"][piexif.ImageIFD.Make] = b"Sony"
    exif["0th"][piexif.ImageIFD.Model] = b"A7 IV"
    return _make_jpeg(tmp_path / "wrong_date.jpg", exif)


@pytest.fixture()
def png_no_exif(tmp_path) -> Path:
    """PNG file — no EXIF, tests extension handling."""
    return _make_png(tmp_path / "image.png")


# ---------------------------------------------------------------------------
# Composite fixture: a source directory with all scenarios
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_source_dir(tmp_path) -> Path:
    """
    A source directory containing one file per scenario plus a nested subdir.

    Layout
    ------
    source/
        full_exif.jpg       – Canon EOS R5, 2023-06-15
        date_only.jpg       – no camera, 2021-12-01
        no_exif.jpg         – no metadata
        wrong_date.jpg      – Sony A7 IV, bad date string
        image.png           – PNG, no EXIF
        subdir/
            nested.jpg      – Nikon Z6, 2020-03-22  (tests recursive walk)
    """
    src = tmp_path / "source"
    src.mkdir()

    # full_exif
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2023:06:15 10:30:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Canon"
    exif["0th"][piexif.ImageIFD.Model] = b"EOS R5"
    _make_jpeg(src / "full_exif.jpg", exif)

    # date_only
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2021:12:01 08:00:00"
    _make_jpeg(src / "date_only.jpg", exif)

    # no_exif
    _make_jpeg(src / "no_exif.jpg", None)

    # wrong_date
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"not-a-date"
    exif["0th"][piexif.ImageIFD.Make] = b"Sony"
    exif["0th"][piexif.ImageIFD.Model] = b"A7 IV"
    _make_jpeg(src / "wrong_date.jpg", exif)

    # png
    _make_png(src / "image.png")

    # nested subdir
    subdir = src / "subdir"
    subdir.mkdir()
    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2020:03:22 14:45:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Nikon"
    exif["0th"][piexif.ImageIFD.Model] = b"Z6"
    _make_jpeg(subdir / "nested.jpg", exif)

    return src
