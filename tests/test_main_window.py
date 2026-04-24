"""Tests for MainWindow layout and scan_complete wiring."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.models.scan_result import ScanResult


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp):
    w = MainWindow()
    yield w
    w.close()


def test_main_window_has_two_tabs(win):
    assert win._tabs.count() == 2


def test_main_window_initial_tab(win):
    assert win._tabs.currentIndex() == 0
    assert win._tabs.currentWidget() is win._scan_tab


def test_main_window_scan_complete_switches_tab(win, qapp):
    result = ScanResult()
    win._scan_tab.scan_complete.emit(Path("/tmp"), result)
    qapp.processEvents()
    assert win._tabs.currentWidget() is win._move_tab


def test_main_window_scan_complete_enables_move(win, qapp):
    result = ScanResult()
    win._scan_tab.scan_complete.emit(Path("/tmp"), result)
    qapp.processEvents()
    assert win._move_tab._move_btn.isEnabled()
