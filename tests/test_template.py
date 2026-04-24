from datetime import datetime
from pathlib import Path

import pytest

from app.core.template import (
    PRESETS,
    ValidationResult,
    render_preview,
    resolve_path,
    validate_template,
)
from app.models.photo_file import PhotoFile


def make_photo(
    date_taken=datetime(2023, 6, 15),
    camera_make="Canon",
    camera_model="EOS R5",
    extension="jpg",
) -> PhotoFile:
    return PhotoFile(
        source_path=Path("test.jpg"),
        extension=extension,
        date_taken=date_taken,
        camera_make=camera_make,
        camera_model=camera_model,
        resolved_dest=None,
        has_metadata=True,
    )


# --- Validation tests ---

def test_valid_date_template():
    result = validate_template("{year}/{month}")
    assert result.is_valid
    assert result.warnings == []


def test_valid_camera_template():
    result = validate_template("{camera}/{year}")
    assert result.is_valid
    assert result.warnings == []


def test_unknown_token():
    result = validate_template("{year}/{foo}")
    assert not result.is_valid
    assert any("foo" in e for e in result.errors)


def test_empty_template():
    result = validate_template("")
    assert not result.is_valid
    assert any("empty" in e.lower() for e in result.errors)


def test_no_date_or_camera_warning():
    result = validate_template("{ext}")
    assert result.is_valid
    assert len(result.warnings) == 1
    assert "collision" in result.warnings[0].lower()


def test_all_presets_valid():
    for preset in PRESETS:
        result = validate_template(preset)
        assert result.is_valid, f"Preset failed: {preset!r} — {result.errors}"


# --- Preview tests ---

def test_preview_date():
    assert render_preview("{year}/{month}/{day}") == "2024/03/07"


def test_preview_camera():
    assert render_preview("{camera}/{year}") == "Canon_EOS_R5/2024"


def test_preview_month_name():
    assert render_preview("{year}/{month_name}") == "2024/March"


def test_preview_unknown_token():
    assert render_preview("{year}/{bogus}") == ""


# --- resolve_path tests ---

def test_resolve_full_metadata():
    photo = make_photo(date_taken=datetime(2023, 6, 15), camera_make="Canon", camera_model="EOS R5")
    assert resolve_path("{year}/{month}/{day}", photo) == Path("2023/06/15")


def test_resolve_no_date_returns_none():
    photo = make_photo(date_taken=None)
    assert resolve_path("{year}/{month}", photo) is None


def test_resolve_unknown_camera():
    photo = make_photo(camera_make=None, camera_model=None)
    assert resolve_path("{camera}", photo) == Path("unknown_camera")


def test_resolve_camera_spaces():
    photo = make_photo(camera_make="Sony Alpha", camera_model="A7 IV")
    assert resolve_path("{camera}", photo) == Path("Sony_Alpha_A7_IV")


def test_resolve_ext():
    photo = make_photo(extension="heic")
    assert resolve_path("{ext}", photo) == Path("heic")
