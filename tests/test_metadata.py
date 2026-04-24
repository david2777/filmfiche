from datetime import datetime
from pathlib import Path

import pytest

from app.core.metadata import extract_metadata


def test_full_exif(jpeg_full_exif: Path):
    result = extract_metadata(jpeg_full_exif)
    assert result.date_taken == datetime(2023, 6, 15, 10, 30, 0)
    assert result.camera_make == "Canon"
    assert result.camera_model == "EOS R5"
    assert result.has_metadata is True


def test_date_only(jpeg_date_only: Path):
    result = extract_metadata(jpeg_date_only)
    assert result.date_taken == datetime(2021, 12, 1, 8, 0, 0)
    assert result.camera_make is None
    assert result.camera_model is None
    assert result.has_metadata is True


def test_no_exif(jpeg_no_exif: Path):
    result = extract_metadata(jpeg_no_exif)
    assert result.date_taken is None
    assert result.has_metadata is False


def test_wrong_date_fmt(jpeg_wrong_date_fmt: Path):
    result = extract_metadata(jpeg_wrong_date_fmt)
    assert result.date_taken is None
    assert result.has_metadata is False


def test_png_no_exif(png_no_exif: Path):
    result = extract_metadata(png_no_exif)
    assert result.date_taken is None
    assert result.extension == "png"
    assert result.has_metadata is False


def test_extension_lowercase(jpeg_full_exif: Path):
    result = extract_metadata(jpeg_full_exif)
    assert result.extension == "jpg"


def test_resolved_dest_is_none(jpeg_full_exif: Path):
    result = extract_metadata(jpeg_full_exif)
    assert result.resolved_dest is None
