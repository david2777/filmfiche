"""Unit tests for app/core/mover.py."""

from pathlib import Path

import piexif
import pytest
from PIL import Image

from app.core.mover import CollisionMode, move_files
from app.core.scanner import scan_directory
from app.models.photo_file import PhotoFile
from datetime import datetime

TEMPLATE = "{year}/{month}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_output_files(output_dir: Path) -> list[Path]:
    return [p for p in output_dir.rglob("*") if p.is_file()]


def _make_dated_photo(tmp_path: Path) -> PhotoFile:
    """Create a single JPEG with full EXIF and return a PhotoFile for it."""
    exif: dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2023:06:15 10:30:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Canon"
    exif["0th"][piexif.ImageIFD.Model] = b"EOS R5"
    path = tmp_path / "full_exif.jpg"
    img = Image.new("RGB", (1, 1))
    img.save(path, format="JPEG", exif=piexif.dump(exif))
    return PhotoFile(
        source_path=path,
        extension="jpg",
        date_taken=datetime(2023, 6, 15, 10, 30, 0),
        camera_make="Canon",
        camera_model="EOS R5",
        resolved_dest=None,
        has_metadata=True,
    )


# ---------------------------------------------------------------------------
# Bulk tests (all 6 files from sample_source_dir)
# ---------------------------------------------------------------------------

def test_move_copy_all_files_exist_in_output(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir)
    assert len(_collect_output_files(output_dir)) == 6


def test_move_copy_preserves_source(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    source_files = [p for p in sample_source_dir.rglob("*") if p.is_file()]
    move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir, copy=True)
    for f in source_files:
        assert f.exists(), f"Source file missing after copy: {f}"


def test_move_move_removes_source(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    source_files = [p for p in sample_source_dir.rglob("*") if p.is_file()]
    move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir, copy=False)
    for f in source_files:
        assert not f.exists(), f"Source file still exists after move: {f}"


def test_move_undated_files_go_to_unknown(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir)
    unknown_dir = output_dir / "_unknown"
    unknown_files = _collect_output_files(unknown_dir)
    # no_exif.jpg, wrong_date.jpg, image.png — 3 undated files
    assert len(unknown_files) == 3


def test_move_dated_files_not_in_unknown(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir)
    unknown_dir = output_dir / "_unknown"
    unknown_names = {f.name for f in _collect_output_files(unknown_dir)}
    dated_names = {"full_exif.jpg", "date_only.jpg", "nested.jpg"}
    assert dated_names.isdisjoint(unknown_names)


def test_move_sets_resolved_dest(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir)
    for photo in scan.files:
        assert photo.resolved_dest is not None


def test_move_result_counts(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    result = move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir)
    assert result.moved == 6
    assert result.skipped == 0


def test_move_log_has_entries(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    result = move_files(scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir)
    assert len(result.log) == 6


def test_move_progress_callback(sample_source_dir, tmp_path):
    output_dir = tmp_path / "output"
    scan = scan_directory(sample_source_dir)
    calls: list[tuple[int, int]] = []
    move_files(
        scan.files, output_dir, TEMPLATE, CollisionMode.SKIP, sample_source_dir,
        progress_callback=lambda cur, tot: calls.append((cur, tot)),
    )
    assert len(calls) == 6
    assert calls[-1] == (6, 6)


# ---------------------------------------------------------------------------
# Collision tests (single file, pre-created destination)
# ---------------------------------------------------------------------------

def test_move_collision_skip(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    output_dir = tmp_path / "output"
    photo = _make_dated_photo(src_dir)

    # Pre-create the destination
    dest = output_dir / "2023" / "06" / "full_exif.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"old")

    result = move_files([photo], output_dir, TEMPLATE, CollisionMode.SKIP, src_dir)
    assert result.skipped == 1
    assert result.moved == 0
    assert dest.read_bytes() == b"old"
    # Source still exists (copy=True by default)
    assert photo.source_path.exists()


def test_move_collision_suffix(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    output_dir = tmp_path / "output"
    photo = _make_dated_photo(src_dir)

    dest = output_dir / "2023" / "06" / "full_exif.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"old")

    result = move_files([photo], output_dir, TEMPLATE, CollisionMode.SUFFIX, src_dir)
    assert result.moved == 1
    assert result.skipped == 0
    suffixed = output_dir / "2023" / "06" / "full_exif_1.jpg"
    assert suffixed.exists()


def test_move_collision_override(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    output_dir = tmp_path / "output"
    photo = _make_dated_photo(src_dir)
    original_content = photo.source_path.read_bytes()

    dest = output_dir / "2023" / "06" / "full_exif.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"old")

    result = move_files([photo], output_dir, TEMPLATE, CollisionMode.OVERRIDE, src_dir)
    assert result.moved == 1
    assert dest.read_bytes() == original_content
