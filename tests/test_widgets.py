"""Unit tests for app/gui/widgets/."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.core.template import PRESETS
from app.gui.widgets.dir_picker import DirPicker
from app.gui.widgets.filter_panel import FilterPanel
from app.gui.widgets.template_editor import TemplateEditor
from app.models.scan_result import ScanResult


# ---------------------------------------------------------------------------
# Session-scoped QApplication (one per test run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """Return an existing or freshly created QApplication instance."""
    app = QApplication.instance() or QApplication([])
    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scan_result() -> ScanResult:
    return ScanResult(
        files=[],
        extension_counts={"jpg": 3, "png": 2},
        camera_counts={"Canon_EOS_R5": 2, "unknown_camera": 1},
    )


# ---------------------------------------------------------------------------
# DirPicker tests
# ---------------------------------------------------------------------------


def test_dir_picker_initial_path_is_none(qapp):
    picker = DirPicker()
    assert picker.path is None


def test_dir_picker_path_changed_signal(qapp, tmp_path):
    picker = DirPicker()
    received: list[Path] = []
    picker.path_changed.connect(received.append)
    picker.set_directory(tmp_path)
    assert received == [tmp_path]
    assert picker.path == tmp_path


# ---------------------------------------------------------------------------
# TemplateEditor tests
# ---------------------------------------------------------------------------


def test_template_editor_initial_is_valid(qapp):
    editor = TemplateEditor()
    assert editor.is_valid


def test_template_editor_preview_updates(qapp):
    editor = TemplateEditor()
    editor._line_edit.setText("{year}/{month}")
    assert "2024/03" in editor._preview_label.text()


def test_template_editor_invalid_token(qapp):
    editor = TemplateEditor()
    editor._line_edit.setText("{bogus}")
    assert not editor.is_valid
    assert editor._status_label.text()  # non-empty error message


def test_template_editor_preset_context_menu(qapp):
    from PySide6.QtCore import Qt
    editor = TemplateEditor()
    assert editor._line_edit.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    editor._line_edit.setText(PRESETS[2])
    assert editor._line_edit.text() == PRESETS[2]


def test_template_editor_signal_emitted(qapp):
    editor = TemplateEditor()
    received: list[str] = []
    editor.template_changed.connect(received.append)
    editor._line_edit.setText("{year}")
    assert received[-1] == "{year}"


# ---------------------------------------------------------------------------
# FilterPanel tests
# ---------------------------------------------------------------------------


def test_filter_panel_populate_extensions(qapp):
    panel = FilterPanel()
    panel.populate(_make_scan_result())
    assert panel.selected_extensions() == {"jpg", "png"}


def test_filter_panel_populate_cameras(qapp):
    panel = FilterPanel()
    panel.populate(_make_scan_result())
    assert panel.selected_cameras() == {"Canon_EOS_R5", "unknown_camera"}


def test_filter_panel_deselect_extension(qapp):
    panel = FilterPanel()
    panel.populate(_make_scan_result())
    panel._ext_checks["jpg"].setChecked(False)
    assert "jpg" not in panel.selected_extensions()
    assert "png" in panel.selected_extensions()


def test_filter_panel_filter_changed_signal(qapp):
    panel = FilterPanel()
    panel.populate(_make_scan_result())
    received: list[bool] = []
    panel.filter_changed.connect(lambda: received.append(True))
    panel._ext_checks["jpg"].setChecked(False)
    assert len(received) == 1


def test_filter_panel_repopulate_clears(qapp):
    panel = FilterPanel()
    sr1 = ScanResult(
        files=[], extension_counts={"jpg": 1}, camera_counts={"CamA": 1}
    )
    sr2 = ScanResult(
        files=[],
        extension_counts={"png": 2, "heic": 3},
        camera_counts={"CamB": 1},
    )
    panel.populate(sr1)
    panel.populate(sr2)
    assert panel.selected_extensions() == {"png", "heic"}
    assert panel.selected_cameras() == {"CamB"}
