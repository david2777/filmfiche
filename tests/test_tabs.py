"""Tests for ScanWorker, ScanTab, MoveWorker, and MoveTab."""

import struct
from datetime import datetime
from pathlib import Path

import piexif
import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.gui.move_tab import MoveTab, MoveWorker
from app.gui.scan_tab import ScanTab, ScanWorker
from app.models.photo_file import PhotoFile
from app.models.scan_result import ScanResult
from app.core.mover import CollisionMode


# ---------------------------------------------------------------------------
# QApplication fixture (session-scoped so Qt initialises once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Return the (possibly already existing) QApplication instance."""
    app = QApplication.instance() or QApplication([])
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_exif() -> dict:
    return {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}


def _make_jpeg(path: Path, exif_dict: dict | None) -> Path:
    img = Image.new("RGB", (1, 1), color=(100, 149, 237))
    kwargs = {}
    if exif_dict is not None:
        kwargs["exif"] = piexif.dump(exif_dict)
    img.save(path, format="JPEG", **kwargs)
    return path


@pytest.fixture()
def sample_source_dir(tmp_path) -> Path:
    """Source directory with 2 JPEG files (one with EXIF, one without)."""
    src = tmp_path / "source"
    src.mkdir()

    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2024:03:07 12:00:00"
    exif["0th"][piexif.ImageIFD.Make] = b"Canon"
    exif["0th"][piexif.ImageIFD.Model] = b"EOS R5"
    _make_jpeg(src / "photo.jpg", exif)

    _make_jpeg(src / "no_exif.jpg", None)

    return src


# ---------------------------------------------------------------------------
# ScanWorker tests
# ---------------------------------------------------------------------------

def test_scan_worker_finished(qapp, sample_source_dir):
    """Worker emits a ScanResult with the scanned files."""
    received = []
    worker = ScanWorker(sample_source_dir)
    worker.finished.connect(lambda r: received.append(r))
    worker.start()
    worker.wait(10_000)
    QApplication.processEvents()

    assert len(received) == 1
    result = received[0]
    assert isinstance(result, ScanResult)
    assert len(result.files) == 2


def test_scan_worker_progress(qapp, sample_source_dir):
    """Worker emits progress signals; last call has current == total."""
    calls = []
    worker = ScanWorker(sample_source_dir)
    worker.progress.connect(lambda c, t: calls.append((c, t)))
    worker.start()
    worker.wait(10_000)
    QApplication.processEvents()

    assert len(calls) > 0
    last_c, last_t = calls[-1]
    assert last_c == last_t


# ---------------------------------------------------------------------------
# ScanTab tests
# ---------------------------------------------------------------------------

def test_scan_tab_initial_state(qapp):
    """ScanTab starts with no source path and an enabled Scan button."""
    tab = ScanTab()
    assert tab.source_path is None
    assert tab._scan_btn.isEnabled()


def test_scan_tab_emits_scan_complete(qapp, sample_source_dir):
    """Clicking Scan triggers a worker and emits scan_complete with a ScanResult."""
    tab = ScanTab()
    received = []
    tab.scan_complete.connect(lambda p, r: received.append((p, r)))

    tab._dir_picker.set_directory(sample_source_dir)
    tab._scan_btn.click()
    tab._worker.wait(10_000)
    QApplication.processEvents()

    assert len(received) == 1
    path, result = received[0]
    assert path == sample_source_dir
    assert isinstance(result, ScanResult)
    assert len(result.files) > 0


# ---------------------------------------------------------------------------
# MoveWorker tests
# ---------------------------------------------------------------------------

def test_move_worker_copy(qapp, tmp_path):
    """MoveWorker copies a single file and emits MoveResult with moved == 1."""
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    exif = _base_exif()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = b"2024:03:07 12:00:00"
    img_path = _make_jpeg(src / "photo.jpg", exif)

    photo = PhotoFile(
        source_path=img_path,
        extension="jpg",
        date_taken=datetime(2024, 3, 7),
        camera_make=None,
        camera_model=None,
        resolved_dest=None,
        has_metadata=True,
    )

    received = []
    worker = MoveWorker(
        files=[photo],
        output_dir=out,
        template="{year}/{month}",
        collision_mode=CollisionMode.SKIP,
        source=src,
        copy=True,
    )
    worker.finished.connect(lambda r: received.append(r))
    worker.start()
    worker.wait(10_000)
    QApplication.processEvents()

    assert len(received) == 1
    result = received[0]
    assert result.moved == 1
    assert result.skipped == 0
    assert result.errors == 0


# ---------------------------------------------------------------------------
# MoveTab tests
# ---------------------------------------------------------------------------

def test_move_tab_initial_state(qapp):
    """MoveTab starts with the Move button disabled."""
    tab = MoveTab()
    assert not tab._move_btn.isEnabled()


def test_move_tab_load_scan_result(qapp, sample_source_dir):
    """After load_scan_result, button is enabled and FilterPanel has checkboxes."""
    from app.core.scanner import scan_directory

    result = scan_directory(sample_source_dir)
    tab = MoveTab()
    tab.load_scan_result(sample_source_dir, result)

    assert tab._move_btn.isEnabled()
    assert len(tab._filter_panel._ext_checks) > 0
    assert len(tab._filter_panel._cam_checks) > 0
