"""Tests for the Film Metadata Tagger dialog and its workers."""

import json
from pathlib import Path

import piexif
import pytest
from PIL import Image
from PySide6.QtCore import QDate, QDateTime, QItemSelectionModel, QTime
from PySide6.QtWidgets import QApplication

from app.gui.tagger_dialog import DateTimePickerDialog, ExportWorker, TaggerDialog
from app.gui.widgets.drop_area import collect_image_paths
from app.gui.widgets.frame_table import (
    EXIF_DT_FORMAT,
    _DATE_COL,
    DateTimeDelegate,
)
from app.models.film_frame import FilmFrame


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Return the (possibly already existing) QApplication instance."""
    return QApplication.instance() or QApplication([])


def _make_jpeg(path: Path) -> Path:
    Image.new("RGB", (8, 8), color=(120, 90, 200)).save(path, format="JPEG")
    return path


def _drain_thumbnails(dialog: TaggerDialog) -> None:
    for worker in list(dialog._thumb_workers):
        worker.wait(5000)
    QApplication.processEvents()


def _two_jpegs(tmp_path: Path) -> list[Path]:
    return [_make_jpeg(tmp_path / "a.jpg"), _make_jpeg(tmp_path / "b.jpg")]


def _select_rows(table, rows: list[int]) -> None:
    """Select whole *rows* in *table* via the selection model."""
    sel = table.selectionModel()
    sel.clearSelection()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row in rows:
        sel.select(table.model().index(row, 0), flags)


# ---------------------------------------------------------------------------
# Adding images
# ---------------------------------------------------------------------------

def test_add_paths_assigns_sequential_image_numbers(qapp, tmp_path):
    """Loading images auto-numbers them 1..N in order."""
    dialog = TaggerDialog()
    dialog._add_paths(_two_jpegs(tmp_path))
    _drain_thumbnails(dialog)

    frames = dialog._table.frames()
    assert [f.entry["ImageNumber"] for f in frames] == [1, 2]


def test_collect_image_paths_sorts_by_filename():
    """Loose files are returned sorted by filename, case-insensitively."""
    out = collect_image_paths([Path("b.JPG"), Path("a.jpg"), Path("c.tif")])
    assert [p.name for p in out] == ["a.jpg", "b.JPG", "c.tif"]


def test_add_paths_orders_by_filename(qapp, tmp_path):
    """Frames are numbered 1..N by filename ascending regardless of input order."""
    b = _make_jpeg(tmp_path / "b.jpg")
    a = _make_jpeg(tmp_path / "a.jpg")
    dialog = TaggerDialog()
    dialog._add_paths(collect_image_paths([b, a]))
    _drain_thumbnails(dialog)

    frames = dialog._table.frames()
    assert [f.source_path.name for f in frames] == ["a.jpg", "b.jpg"]
    assert [f.entry["ImageNumber"] for f in frames] == [1, 2]


def test_reverse_order_reverses_and_renumbers(qapp, tmp_path):
    """Reverse flips the sequence and renumbers the last file to #1."""
    paths = [_make_jpeg(tmp_path / f"{c}.jpg") for c in "abc"]
    dialog = TaggerDialog()
    dialog._add_paths(collect_image_paths(paths))
    _drain_thumbnails(dialog)

    assert dialog._reverse_btn.isEnabled()  # enabled once images load
    dialog._on_reverse()

    frames = dialog._table.frames()
    assert [f.source_path.name for f in frames] == ["c.jpg", "b.jpg", "a.jpg"]
    assert [f.entry["ImageNumber"] for f in frames] == [1, 2, 3]


def test_reverse_fixes_inverted_json_pairing(qapp, tmp_path):
    """After Reverse, JSON entries pair to images in the flipped direction."""
    paths = [_make_jpeg(tmp_path / "a.jpg"), _make_jpeg(tmp_path / "b.jpg")]
    dialog = TaggerDialog()
    dialog._add_paths(collect_image_paths(paths))
    _drain_thumbnails(dialog)
    dialog._on_reverse()  # rows now b, a

    entries = [
        {"ReelName": "1003", "ImageNumber": 1, "DateTimeOriginal": "2026:05:05 20:04:14"},
        {"ReelName": "1003", "ImageNumber": 2, "DateTimeOriginal": "2026:05:06 06:38:37"},
    ]
    json_path = tmp_path / "meta.json"
    json_path.write_text(json.dumps(entries), encoding="utf-8")
    dialog._apply_json(str(json_path))

    frames = dialog._table.frames()
    assert frames[0].source_path.name == "b.jpg"
    assert frames[0].entry["DateTimeOriginal"] == "2026:05:05 20:04:14"


def test_export_disabled_until_reel_and_images(qapp, tmp_path):
    """Export turns on only with both images loaded and a Reel Name set."""
    dialog = TaggerDialog()
    assert not dialog._export_btn.isEnabled()

    dialog._add_paths(_two_jpegs(tmp_path))
    _drain_thumbnails(dialog)
    dialog._reel.setText("")  # ensure no leftover persisted reel
    assert not dialog._export_btn.isEnabled()

    dialog._reel.setText("1003")
    assert dialog._export_btn.isEnabled()


# ---------------------------------------------------------------------------
# JSON import
# ---------------------------------------------------------------------------

def test_apply_json_fills_globals_and_cells(qapp, tmp_path):
    """Importing JSON populates the global fields and per-frame entries."""
    dialog = TaggerDialog()
    dialog._add_paths(_two_jpegs(tmp_path))
    _drain_thumbnails(dialog)

    entries = [
        {
            "Make": "Olympus",
            "Model": "OM-2n",
            "ReelName": "1003",
            "DocumentName": "Kodak Gold 200",
            "SpectralSensitivity": "Kodak Gold 200",
            "ISO": 200,
            "ImageNumber": 1,
            "DateTimeOriginal": "2026:05:05 20:04:14",
            "LensModel": "Zuiko 50mm",
        },
        {
            "ReelName": "1003",
            "ImageNumber": 2,
            "DateTimeOriginal": "2026:05:06 06:38:37",
            "FNumber": 2.8,
        },
    ]
    json_path = tmp_path / "meta.json"
    json_path.write_text(json.dumps(entries), encoding="utf-8")

    dialog._apply_json(str(json_path))

    assert dialog._make.text() == "Olympus"
    assert dialog._reel.text() == "1003"
    assert dialog._film.text() == "Kodak Gold 200"
    assert dialog._iso.text() == "200"

    frames = dialog._table.frames()
    assert frames[0].entry["DateTimeOriginal"] == "2026:05:05 20:04:14"
    assert frames[1].entry["FNumber"] == 2.8


def test_apply_json_before_images_is_noop_guarded(qapp, tmp_path):
    """Import is rejected (no crash) when no images are loaded yet."""
    dialog = TaggerDialog()
    dialog._on_import_json()  # should just set a status message
    assert "Add images" in dialog._status.text()


# ---------------------------------------------------------------------------
# ExportWorker
# ---------------------------------------------------------------------------

def test_export_worker_writes_renamed_tagged_files(qapp, tmp_path):
    """ExportWorker writes {reel}-{document}/{reel}-NNNN.jpg with EXIF."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    frames = [
        FilmFrame(_make_jpeg(src_dir / "a.jpg"), {"ImageNumber": 1, "LensModel": "50mm"}),
        FilmFrame(_make_jpeg(src_dir / "b.jpg"), {"ImageNumber": 2}),
    ]
    globals_dict = {
        "Make": "Olympus",
        "Model": "OM-2n",
        "ReelName": "1003",
        "DocumentName": "Kodak Gold 200",
    }

    received = []
    worker = ExportWorker(frames, globals_dict, out_dir)
    worker.finished.connect(lambda n: received.append(n))
    worker.start()
    worker.wait(10_000)
    QApplication.processEvents()

    assert received == [2]
    reel_dir = out_dir / "1003-Kodak_Gold_200"
    first = reel_dir / "1003-0001.jpg"
    second = reel_dir / "1003-0002.jpg"
    assert first.exists() and second.exists()

    loaded = piexif.load(str(first))
    assert loaded["0th"][piexif.ImageIFD.Make] == b"Olympus"
    assert loaded["Exif"][piexif.ExifIFD.LensModel] == b"50mm"


def test_export_worker_errors_without_reel(qapp, tmp_path):
    """Missing ReelName is reported via the error signal, not raised."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    frames = [FilmFrame(_make_jpeg(src_dir / "a.jpg"), {"ImageNumber": 1})]

    errors = []
    worker = ExportWorker(frames, {}, tmp_path / "out")
    worker.error.connect(lambda m: errors.append(m))
    worker.start()
    worker.wait(10_000)
    QApplication.processEvents()

    assert errors and "Reel Name" in errors[0]


# ---------------------------------------------------------------------------
# Date editing
# ---------------------------------------------------------------------------

def test_date_column_uses_datetime_delegate(qapp, tmp_path):
    """The Date column edits through a DateTimeDelegate, not a plain text cell."""
    dialog = TaggerDialog()
    dialog._add_paths(_two_jpegs(tmp_path))
    _drain_thumbnails(dialog)
    assert isinstance(dialog._table.itemDelegateForColumn(_DATE_COL), DateTimeDelegate)


def test_date_delegate_writes_exif_format(qapp, tmp_path):
    """Editing via the delegate stores the EXIF YYYY:MM:DD HH:MM:SS string."""
    dialog = TaggerDialog()
    dialog._add_paths(_two_jpegs(tmp_path))
    _drain_thumbnails(dialog)
    table = dialog._table
    delegate = table.itemDelegateForColumn(_DATE_COL)
    index = table.model().index(0, _DATE_COL)

    editor = delegate.createEditor(table, None, index)
    editor.setDateTime(QDateTime(QDate(2026, 5, 9), QTime(15, 8, 49)))
    delegate.setModelData(editor, table.model(), index)

    assert table.frames()[0].entry["DateTimeOriginal"] == "2026:05:09 15:08:49"


def test_date_delegate_seeds_editor_from_existing_value(qapp, tmp_path):
    """Opening the editor pre-selects the frame's current datetime."""
    dialog = TaggerDialog()
    dialog._add_paths(_two_jpegs(tmp_path))
    _drain_thumbnails(dialog)
    table = dialog._table
    table.frames()[0].entry["DateTimeOriginal"] = "2020:01:02 03:04:05"
    table.refresh()

    delegate = table.itemDelegateForColumn(_DATE_COL)
    index = table.model().index(0, _DATE_COL)
    editor = delegate.createEditor(table, None, index)
    delegate.setEditorData(editor, index)

    assert editor.dateTime().toString(EXIF_DT_FORMAT) == "2020:01:02 03:04:05"


def test_datetime_picker_returns_exif_format(qapp):
    """The picker dialog exposes its value as an EXIF-formatted string."""
    dlg = DateTimePickerDialog(QDateTime(QDate(2026, 6, 18), QTime(9, 30, 0)))
    assert dlg.value() == "2026:06:18 09:30:00"


def test_set_datetime_for_selected_applies_only_to_selection(qapp, tmp_path):
    """Set Date writes the value to selected frames and leaves the rest alone."""
    paths = [_make_jpeg(tmp_path / f"{c}.jpg") for c in "abc"]
    dialog = TaggerDialog()
    dialog._add_paths(collect_image_paths(paths))
    _drain_thumbnails(dialog)
    table = dialog._table
    _select_rows(table, [0, 2])

    count = table.set_datetime_for_selected("2026:05:09 15:08:49")

    assert count == 2
    frames = table.frames()
    assert frames[0].entry["DateTimeOriginal"] == "2026:05:09 15:08:49"
    assert frames[2].entry["DateTimeOriginal"] == "2026:05:09 15:08:49"
    assert "DateTimeOriginal" not in frames[1].entry


def test_set_date_button_tracks_selection(qapp, tmp_path):
    """The Set Date button enables only while at least one row is selected."""
    dialog = TaggerDialog()
    assert not dialog._set_date_btn.isEnabled()

    dialog._add_paths(_two_jpegs(tmp_path))
    _drain_thumbnails(dialog)
    assert not dialog._set_date_btn.isEnabled()  # nothing selected yet

    _select_rows(dialog._table, [0])
    assert dialog._set_date_btn.isEnabled()

    dialog._table.selectionModel().clearSelection()
    assert not dialog._set_date_btn.isEnabled()
