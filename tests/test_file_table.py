"""Tests for the scan-results table model, proxy, and view widget."""

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.gui.widgets.file_table import (
    FileFilterProxyModel,
    FileTableModel,
    FileTableView,
)
from app.models.photo_file import PhotoFile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """Return an existing or freshly created QApplication instance."""
    return QApplication.instance() or QApplication([])


def _photo(name: str, ext: str = "jpg", make=None, model=None, dt=None) -> PhotoFile:
    return PhotoFile(
        source_path=Path("/src") / name,
        extension=ext,
        date_taken=dt,
        camera_make=make,
        camera_model=model,
        resolved_dest=None,
        has_metadata=dt is not None,
    )


@pytest.fixture()
def photos() -> list[PhotoFile]:
    return [
        _photo("a.jpg", "jpg", "Canon", "EOS R5", datetime(2024, 3, 7, 12, 0, 0)),
        _photo("b.png", "png", None, None, None),
        _photo("c.jpg", "jpg", "Nikon", "Z6", datetime(2020, 1, 1, 9, 30, 0)),
    ]


# ---------------------------------------------------------------------------
# FileTableModel
# ---------------------------------------------------------------------------


def test_model_dimensions_and_display(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)

    assert model.rowCount() == 3
    assert model.columnCount() == 4

    assert model.data(model.index(0, 0)) == "a.jpg"
    assert model.data(model.index(0, 1)) == "2024-03-07 12:00:00"
    assert model.data(model.index(0, 2)) == "Canon EOS R5"
    # No date → empty date cell; no camera → unknown_camera.
    assert model.data(model.index(1, 1)) == ""
    assert model.data(model.index(1, 2)) == "unknown_camera"


def test_model_set_files_resets_all_checked(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)
    assert model.checked_count() == 3
    assert all(model.is_checked(r) for r in range(3))


def test_model_toggle_check_via_setdata(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)

    assert model.data(model.index(0, 0), Qt.ItemDataRole.CheckStateRole) == (
        Qt.CheckState.Checked
    )
    ok = model.setData(
        model.index(0, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole
    )
    assert ok
    assert not model.is_checked(0)
    assert model.checked_count() == 2
    assert model.data(model.index(0, 0), Qt.ItemDataRole.CheckStateRole) == (
        Qt.CheckState.Unchecked
    )


def test_model_setdata_accepts_int_state(qapp, photos):
    """Views may pass the raw int check-state value."""
    model = FileTableModel()
    model.set_files(photos)
    model.setData(
        model.index(2, 0),
        int(Qt.CheckState.Unchecked.value),
        Qt.ItemDataRole.CheckStateRole,
    )
    assert not model.is_checked(2)


def test_model_set_checked_for_rows(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)
    model.set_checked_for_rows([0, 2], False)
    assert model.checked_count() == 1
    assert model.is_checked(1)


def test_model_output_column_uses_resolver(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)
    assert model.data(model.index(0, 3)) == ""  # no resolver yet

    model.set_resolver(lambda p: f"out/{p.source_path.name}")
    assert model.data(model.index(0, 3)) == "out/a.jpg"
    assert model.data(model.index(1, 3)) == "out/b.png"


def test_model_name_column_is_checkable(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)
    assert model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsUserCheckable
    assert not (model.flags(model.index(0, 1)) & Qt.ItemFlag.ItemIsUserCheckable)


# ---------------------------------------------------------------------------
# FileFilterProxyModel
# ---------------------------------------------------------------------------


def test_proxy_filter_by_extension(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_allowed({"jpg"}, None)
    assert proxy.rowCount() == 2  # a.jpg, c.jpg

    proxy.set_allowed(None, None)
    assert proxy.rowCount() == 3


def test_proxy_filter_by_camera(qapp, photos):
    model = FileTableModel()
    model.set_files(photos)
    proxy = FileFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.set_allowed(None, {"Canon EOS R5"})
    assert proxy.rowCount() == 1


# ---------------------------------------------------------------------------
# FileTableView
# ---------------------------------------------------------------------------


def test_view_checked_visible_respects_filter_and_checks(qapp, photos):
    view = FileTableView()
    view.set_files(photos)

    # All three checked, no filter → all returned.
    assert len(view.checked_visible_files()) == 3

    # Hide PNGs: only the two jpgs remain selectable.
    view.set_filter({"jpg"}, None)
    names = [p.source_path.name for p in view.checked_visible_files()]
    assert names == ["a.jpg", "c.jpg"]

    # Unchecking a hidden row has no effect on the filtered jpgs.
    view._model.set_checked_for_rows([0], False)  # a.jpg
    names = [p.source_path.name for p in view.checked_visible_files()]
    assert names == ["c.jpg"]


def test_view_select_all_none_operate_on_visible(qapp, photos):
    view = FileTableView()
    view.set_files(photos)
    view.set_filter({"jpg"}, None)

    view._set_visible_checked(False)
    assert view._model.checked_count() == 1  # only the hidden png stays checked

    view._set_visible_checked(True)
    assert view._model.checked_count() == 3


def test_view_count_label_updates(qapp, photos):
    view = FileTableView()
    view.set_files(photos)
    assert "3 of 3 selected" in view._count_label.text()

    view._set_visible_checked(False)
    assert "0 of 3 selected" in view._count_label.text()


def test_view_warns_about_checked_rows_hidden_by_filter(qapp, photos):
    view = FileTableView()
    view.set_files(photos)  # a.jpg, b.png, c.jpg all checked

    # Nothing hidden: terse label, warning hidden.
    assert view.hidden_selected_count() == 0
    assert not view._warning_label.isVisibleTo(view)
    assert view._count_label.text() == "3 of 3 selected"

    # Hide the single checked PNG → 2 will move, 1 hidden (singular wording).
    view.set_filter({"jpg"}, None)
    assert view.hidden_selected_count() == 1
    assert view._count_label.text() == "2 to move · 3 selected · 1 hidden"
    assert view._warning_label.isVisibleTo(view)
    assert "1 selected file is hidden" in view._warning_label.text()

    # Hide both checked JPGs → 1 will move, 2 hidden (plural wording).
    view.set_filter({"png"}, None)
    assert view.hidden_selected_count() == 2
    assert view._count_label.text() == "1 to move · 3 selected · 2 hidden"
    assert "2 selected files are hidden" in view._warning_label.text()

    # Clearing the filter restores the terse label and hides the warning.
    view.set_filter(None, None)
    assert view.hidden_selected_count() == 0
    assert view._count_label.text() == "3 of 3 selected"
    assert not view._warning_label.isVisibleTo(view)


def test_view_selection_changed_signal(qapp, photos):
    view = FileTableView()
    view.set_files(photos)
    received = []
    view.selection_changed.connect(lambda: received.append(True))
    view._model.setData(
        view._model.index(0, 0),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert received
