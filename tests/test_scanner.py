"""Unit tests for app.core.scanner."""

from pathlib import Path

import pytest

from app.core.scanner import scan_directory


def test_scan_total_files(sample_source_dir):
    result = scan_directory(sample_source_dir)
    assert len(result.files) == 6


def test_scan_extension_counts(sample_source_dir):
    result = scan_directory(sample_source_dir)
    assert result.extension_counts == {"jpg": 5, "png": 1}


def test_scan_camera_counts_has_canon(sample_source_dir):
    result = scan_directory(sample_source_dir)
    assert result.camera_counts.get("Canon EOS R5") == 1


def test_scan_camera_counts_has_nikon(sample_source_dir):
    result = scan_directory(sample_source_dir)
    assert result.camera_counts.get("Nikon Z6") == 1


def test_scan_camera_counts_unknown(sample_source_dir):
    result = scan_directory(sample_source_dir)
    # no_exif + wrong_date (bad date → no make/model stored) + date_only = at least 1
    assert "unknown_camera" in result.camera_counts


def test_scan_ignores_unsupported(sample_source_dir):
    (sample_source_dir / "readme.txt").write_text("ignore me")
    result = scan_directory(sample_source_dir)
    assert len(result.files) == 6


def test_scan_nested_subdir(sample_source_dir):
    result = scan_directory(sample_source_dir)
    names = [p.source_path.name for p in result.files]
    assert "nested.jpg" in names


def test_scan_all_source_paths_exist(sample_source_dir):
    result = scan_directory(sample_source_dir)
    assert all(photo.source_path.exists() for photo in result.files)


def test_scan_progress_callback(sample_source_dir):
    calls = []
    scan_directory(sample_source_dir, progress_callback=lambda c, t: calls.append((c, t)))
    assert len(calls) == 6
    assert calls[-1] == (6, 6)
