"""Editable per-frame metadata grid with thumbnails.

A roll of film is only a few dozen frames, so this uses a plain
:class:`QTableWidget` with editable cells rather than the model/view machinery in
:mod:`app.gui.widgets.file_table` (which exists to stay responsive with thousands
of scanned files). Edits are written straight back into each
:class:`~app.models.film_frame.FilmFrame`'s ``entry`` dict; keys that are present
in a frame but not shown as a column (imported from JSON, e.g. ``LensMake`` or the
GPS refs) are preserved untouched.

The Date column uses a :class:`DateTimeDelegate` so editing it opens a calendar /
spin editor that can only produce a valid EXIF ``YYYY:MM:DD HH:MM:SS`` string,
rather than free text.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QDateTime, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateTimeEdit,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
)

from app.models.film_frame import FilmFrame

_THUMB_PX = 96

# Qt display/parse format mirroring the EXIF ``DateTimeOriginal`` string layout.
EXIF_DT_FORMAT = "yyyy:MM:dd HH:mm:ss"

# (header label, entry key). ``None`` = thumbnail column (icon only);
# ``"_file"`` = read-only source filename; any other string is an editable
# per-item EXIF key written back into ``FilmFrame.entry``.
_COLUMNS: tuple[tuple[str, str | None], ...] = (
    ("", None),
    ("#", "ImageNumber"),
    ("File", "_file"),
    ("Date", "DateTimeOriginal"),
    ("Lens", "LensModel"),
    ("Aperture", "FNumber"),
    ("Shutter", "ExposureTime"),
    ("Focal", "FocalLength"),
    ("Notes", "Notes"),
    ("GPS Lat", "GPSLatitude"),
    ("GPS Lon", "GPSLongitude"),
)
_THUMB_COL = 0
_DATE_KEY = "DateTimeOriginal"
_DATE_COL = next(i for i, (_, key) in enumerate(_COLUMNS) if key == _DATE_KEY)


class DateTimeDelegate(QStyledItemDelegate):
    """In-cell editor that constrains the Date column to a valid datetime.

    Opens a :class:`QDateTimeEdit` (with a calendar popup) instead of a free-text
    field, and reads/writes the value in the EXIF ``YYYY:MM:DD HH:MM:SS`` form so
    it round-trips unchanged through :func:`~app.core.tagger.build_exif`.
    """

    def createEditor(self, parent, option, index):
        """Return a calendar-backed datetime spin editor."""
        editor = QDateTimeEdit(parent)
        editor.setDisplayFormat(EXIF_DT_FORMAT)
        editor.setCalendarPopup(True)
        return editor

    def setEditorData(self, editor, index):
        """Seed the editor from the cell, falling back to *now* if blank/invalid."""
        text = index.data(Qt.ItemDataRole.EditRole) or ""
        dt = QDateTime.fromString(str(text), EXIF_DT_FORMAT)
        if not dt.isValid():
            dt = QDateTime.currentDateTime()
        editor.setDateTime(dt)

    def setModelData(self, editor, model, index):
        """Write the chosen datetime back as an EXIF-formatted string."""
        editor.interpretText()
        model.setData(
            index,
            editor.dateTime().toString(EXIF_DT_FORMAT),
            Qt.ItemDataRole.EditRole,
        )


class FrameTable(QTableWidget):
    """Grid of frames: thumbnail + editable per-item metadata cells."""

    def __init__(self, parent=None):
        """Initialise an empty frame table.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(0, len(_COLUMNS), parent)
        self._frames: list[FilmFrame] = []
        # Thumbnails are cached by frame identity (id) rather than row index so
        # they survive a reverse_order() and never land on the wrong row if a
        # load finishes after the frames have been reordered.
        self._thumb_cache: dict[int, QIcon] = {}
        self._populating = False

        self.setHorizontalHeaderLabels([label for label, _ in _COLUMNS])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setIconSize(QSize(_THUMB_PX, _THUMB_PX))
        self.setColumnWidth(_THUMB_COL, _THUMB_PX + 8)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(_THUMB_PX + 8)
        self.horizontalHeader().setStretchLastSection(True)

        self.setItemDelegateForColumn(_DATE_COL, DateTimeDelegate(self))
        self.itemChanged.connect(self._on_item_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def frames(self) -> list[FilmFrame]:
        """Return the backing list of frames (live; reflects edits)."""
        return self._frames

    def add_frames(self, frames: Iterable[FilmFrame]) -> None:
        """Append *frames*, auto-numbering any without an ``ImageNumber``."""
        self._populating = True
        try:
            for frame in frames:
                row = self.rowCount()
                self.insertRow(row)
                frame.entry.setdefault("ImageNumber", row + 1)
                self._frames.append(frame)
                self._populate_row(row, frame)
        finally:
            self._populating = False

    def reverse_order(self) -> None:
        """Reverse the frame sequence and renumber 1..N top-to-bottom.

        Used when the scan direction is the opposite of the metadata order: the
        last file becomes ``ImageNumber`` 1. Cached thumbnails follow their
        frames, so no re-decoding is needed.
        """
        if not self._frames:
            return
        self._frames.reverse()
        self._populating = True
        try:
            self.setRowCount(0)
            for row, frame in enumerate(self._frames):
                self.insertRow(row)
                frame.entry["ImageNumber"] = row + 1
                self._populate_row(row, frame)
        finally:
            self._populating = False

    def selected_frames(self) -> list[FilmFrame]:
        """Return the frames for the currently selected rows, in row order."""
        rows = sorted(idx.row() for idx in self.selectionModel().selectedRows())
        return [self._frames[row] for row in rows]

    def set_datetime_for_selected(self, value: str) -> int:
        """Set ``DateTimeOriginal`` on every selected row to *value*.

        Writes through the Date cell so the normal edit path updates each frame's
        ``entry`` dict.

        Args:
            value: An EXIF-formatted datetime string (``YYYY:MM:DD HH:MM:SS``).

        Returns:
            The number of frames updated.
        """
        rows = sorted(idx.row() for idx in self.selectionModel().selectedRows())
        for row in rows:
            item = self.item(row, _DATE_COL)
            if item is not None:
                item.setText(value)
        return len(rows)

    def set_thumbnail(self, frame: FilmFrame, image: QImage) -> None:
        """Cache and display the thumbnail for *frame* from a ``QImage``."""
        icon = QIcon(QPixmap.fromImage(image))
        self._thumb_cache[id(frame)] = icon
        for row, candidate in enumerate(self._frames):
            if candidate is frame:
                item = self.item(row, _THUMB_COL)
                if item is not None:
                    item.setIcon(icon)
                return

    def refresh(self) -> None:
        """Repaint all editable cells from the frames (e.g. after JSON import)."""
        self._populating = True
        try:
            for row, frame in enumerate(self._frames):
                for col, (_, key) in enumerate(_COLUMNS):
                    if key in (None, "_file"):
                        continue
                    item = self.item(row, col)
                    if item is not None:
                        item.setText(self._cell_text(frame, key))
        finally:
            self._populating = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _cell_text(frame: FilmFrame, key: str) -> str:
        value = frame.entry.get(key)
        return "" if value is None else str(value)

    def _populate_row(self, row: int, frame: FilmFrame) -> None:
        for col, (_, key) in enumerate(_COLUMNS):
            if key is None:
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                icon = self._thumb_cache.get(id(frame))
                if icon is not None:
                    item.setIcon(icon)
            elif key == "_file":
                item = QTableWidgetItem(frame.source_path.name)
                item.setToolTip(str(frame.source_path))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            else:
                item = QTableWidgetItem(self._cell_text(frame, key))
            self.setItem(row, col, item)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating:
            return
        _, key = _COLUMNS[item.column()]
        if key in (None, "_file"):
            return
        frame = self._frames[item.row()]
        text = item.text().strip()
        if text:
            frame.entry[key] = text
        else:
            frame.entry.pop(key, None)
