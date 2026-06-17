"""Editable per-frame metadata grid with thumbnails.

A roll of film is only a few dozen frames, so this uses a plain
:class:`QTableWidget` with editable cells rather than the model/view machinery in
:mod:`app.gui.widgets.file_table` (which exists to stay responsive with thousands
of scanned files). Edits are written straight back into each
:class:`~app.models.film_frame.FilmFrame`'s ``entry`` dict; keys that are present
in a frame but not shown as a column (imported from JSON, e.g. ``LensMake`` or the
GPS refs) are preserved untouched.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

from app.models.film_frame import FilmFrame

_THUMB_PX = 96

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
