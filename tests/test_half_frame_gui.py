"""Tests for the Half Frame Splitter dialog and its worker."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from app.gui.half_frame_dialog import HalfFrameDialog, SplitWorker
from app.models.split_result import SplitResult


@pytest.fixture(scope="session")
def qapp():
    """Return the (possibly already existing) QApplication instance."""
    return QApplication.instance() or QApplication([])


def _make_scan(path: Path, w: int = 800, h: int = 600) -> Path:
    rng = np.random.default_rng(1)
    arr = np.empty((h, w, 3), dtype=np.uint8)
    mid = w // 2
    arr[:, :mid] = rng.normal(80, 40, (h, mid, 3)).clip(0, 255).astype(np.uint8)
    arr[:, mid:] = rng.normal(200, 40, (h, w - mid, 3)).clip(0, 255).astype(np.uint8)
    arr[:, mid - 15: mid + 15] = 128
    Image.fromarray(arr).save(path)
    return path


def _input_with_scans(tmp_path: Path, n: int = 2) -> Path:
    src = tmp_path / "in"
    src.mkdir()
    for i in range(n):
        _make_scan(src / f"scan{i}.jpg")
    return src


# ---------------------------------------------------------------------------
# SplitWorker
# ---------------------------------------------------------------------------

def test_split_worker_processes_folder(qapp, tmp_path):
    """Worker splits every scan and reports counts; outputs land in the out dir."""
    src = _input_with_scans(tmp_path, 2)
    out = tmp_path / "out"
    out.mkdir()

    received = []
    worker = SplitWorker(src, out, mode="auto", search_frac=0.30, gap=0)
    worker.finished.connect(lambda r: received.append(r))
    worker.start()
    worker.wait(20_000)
    QApplication.processEvents()

    assert len(received) == 1
    result = received[0]
    assert isinstance(result, SplitResult)
    assert result.processed == 2
    assert result.written == 4
    assert result.errors == 0

    names = sorted(p.name for p in out.iterdir())
    assert names == ["scan0-a.jpg", "scan0-b.jpg", "scan1-a.jpg", "scan1-b.jpg"]


def test_split_worker_empty_folder(qapp, tmp_path):
    """An input folder with no supported scans yields an all-zero result."""
    src = tmp_path / "in"
    src.mkdir()
    out = tmp_path / "out"
    out.mkdir()

    received = []
    worker = SplitWorker(src, out, mode="auto", search_frac=0.30, gap=0)
    worker.finished.connect(lambda r: received.append(r))
    worker.start()
    worker.wait(10_000)
    QApplication.processEvents()

    assert received[0].processed == 0
    assert received[0].written == 0


# ---------------------------------------------------------------------------
# HalfFrameDialog
# ---------------------------------------------------------------------------

def test_dialog_enables_split_when_both_folders_set(qapp, tmp_path):
    src = _input_with_scans(tmp_path, 1)
    out = tmp_path / "out"
    out.mkdir()

    dialog = HalfFrameDialog()
    dialog._input_picker.set_directory(src)
    dialog._output_picker.set_directory(out)
    assert dialog._split_btn.isEnabled()


def test_dialog_center_mode_disables_search_window(qapp):
    dialog = HalfFrameDialog()
    dialog._center_radio.setChecked(True)
    assert not dialog._search_spin.isEnabled()
    dialog._auto_radio.setChecked(True)
    assert dialog._search_spin.isEnabled()


def test_dialog_split_runs_end_to_end(qapp, tmp_path):
    """Driving the dialog's Split button writes the four outputs."""
    src = _input_with_scans(tmp_path, 2)
    out = tmp_path / "out"
    out.mkdir()

    dialog = HalfFrameDialog()
    dialog._input_picker.set_directory(src)
    dialog._output_picker.set_directory(out)
    dialog._on_split()
    dialog._worker.wait(20_000)
    QApplication.processEvents()

    assert len(list(out.iterdir())) == 4
    assert "Split 2 scan(s)" in dialog._status.text()
