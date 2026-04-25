"""Tests for MainWindow layout and scan_complete wiring."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.models.scan_result import ScanResult


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("filmfiche_test")
    app.setApplicationName("filmfiche_test")
    yield app
    QSettings().clear()


@pytest.fixture
def win(qapp):
    w = MainWindow()
    yield w
    w.close()


def test_main_window_has_scan_and_move_sections(win):
    assert win._scan_tab is not None
    assert win._move_tab is not None


def test_main_window_move_section_initially_disabled(win):
    assert not win._move_tab.isEnabled()


def test_main_window_scan_complete_enables_move(win, qapp):
    result = ScanResult()
    win._scan_tab.scan_complete.emit(Path("/tmp"), result)
    qapp.processEvents()
    assert win._move_tab.isEnabled()
    assert not win._move_tab._move_btn.isEnabled()  # output path not yet set


def test_main_window_move_btn_enables_with_output_path(win, qapp, tmp_path):
    result = ScanResult()
    win._scan_tab.scan_complete.emit(Path("/tmp"), result)
    qapp.processEvents()
    win._move_tab._dir_picker.set_directory(tmp_path)
    qapp.processEvents()
    assert win._move_tab._move_btn.isEnabled()
