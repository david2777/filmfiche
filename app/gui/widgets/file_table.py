"""Model/view table for scan results with per-row selection and out-path preview.

This module is built on Qt's model/view framework rather than item widgets so it
stays responsive with thousands of files: only the rows currently scrolled into
view are ever painted, and selection state is stored as a flat ``list[bool]``.

Three pieces:

* :class:`FileTableModel` — wraps ``list[PhotoFile]`` plus a parallel checked
  state, exposing Name (with checkbox), Date, Camera, and Output Path columns.
* :class:`FileFilterProxyModel` — hides rows whose extension or camera is not in
  the allowed sets supplied by the :class:`~app.gui.widgets.filter_panel.FilterPanel`.
* :class:`FileTableView` — the user-facing widget bundling the table, a
  select-all/none toolbar, and a live selection count.
"""

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.core.scanner import _camera_key
from app.models.photo_file import PhotoFile

# Resolver maps a PhotoFile to its previewed output path (or ``None`` if it
# cannot be computed yet, e.g. no output directory selected). The return value
# is stringified for display, so ``Path`` or ``str`` are both acceptable.
DestResolver = Callable[[PhotoFile], Any]


class FileTableModel(QAbstractTableModel):
    """Table model exposing scanned files with a per-row checkbox.

    Columns:
        0. Name — file name, with a user-checkable checkbox controlling selection.
        1. Date — capture timestamp (``YYYY-MM-DD HH:MM:SS``) or empty.
        2. Camera — combined make/model key.
        3. Output Path — previewed destination, supplied by a resolver callback.

    Attributes:
        COLUMNS: Ordered column header labels.
    """

    COLUMNS = ("Name", "Date", "Camera", "Output Path")
    _NAME_COL = 0
    _OUTPUT_COL = 3

    def __init__(self, parent=None):
        """Initialise an empty model.

        Args:
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._files: list[PhotoFile] = []
        self._checked: list[bool] = []
        self._resolver: DestResolver | None = None

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def set_files(self, files: Iterable[PhotoFile]) -> None:
        """Replace all rows, resetting every file to checked.

        Args:
            files: The new ``PhotoFile`` objects to display.
        """
        self.beginResetModel()
        self._files = list(files)
        self._checked = [True] * len(self._files)
        self.endResetModel()

    def set_resolver(self, resolver: DestResolver | None) -> None:
        """Set the callback used to compute the Output Path column and refresh it.

        Args:
            resolver: A callable mapping a ``PhotoFile`` to its previewed
                destination, or ``None`` to blank the column.
        """
        self._resolver = resolver
        self.refresh_output()

    def refresh_output(self) -> None:
        """Signal that the Output Path column should be repainted for all rows."""
        if not self._files:
            return
        top = self.index(0, self._OUTPUT_COL)
        bottom = self.index(self.rowCount() - 1, self._OUTPUT_COL)
        self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def photo_at(self, row: int) -> PhotoFile:
        """Return the ``PhotoFile`` backing *row*."""
        return self._files[row]

    def is_checked(self, row: int) -> bool:
        """Return whether *row* is currently checked."""
        return self._checked[row]

    def checked_count(self) -> int:
        """Return the number of checked rows."""
        return sum(self._checked)

    def set_checked_for_rows(self, rows: Iterable[int], checked: bool) -> None:
        """Set the checked state of several source rows at once.

        Args:
            rows: Source-model row indices to update.
            checked: ``True`` to check, ``False`` to uncheck.
        """
        rows = [r for r in rows if 0 <= r < len(self._checked)]
        if not rows:
            return
        for r in rows:
            self._checked[r] = checked
        top = self.index(min(rows), self._NAME_COL)
        bottom = self.index(max(rows), self._NAME_COL)
        self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.CheckStateRole])

    # ------------------------------------------------------------------
    # QAbstractTableModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the number of files (0 for a valid parent — this is flat)."""
        return 0 if parent.isValid() else len(self._files)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Return the fixed column count."""
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        """Return cell data for *index* and *role*."""
        if not index.isValid():
            return None
        photo = self._files[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.CheckStateRole and col == self._NAME_COL:
            return (
                Qt.CheckState.Checked
                if self._checked[index.row()]
                else Qt.CheckState.Unchecked
            )

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._display_for(photo, col)

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == self._NAME_COL:
                return str(photo.source_path)
            if col == self._OUTPUT_COL:
                dest = self._resolver(photo) if self._resolver else None
                return str(dest) if dest is not None else ""

        return None

    def _display_for(self, photo: PhotoFile, col: int) -> str:
        if col == self._NAME_COL:
            return photo.source_path.name
        if col == 1:
            return (
                photo.date_taken.strftime("%Y-%m-%d %H:%M:%S")
                if photo.date_taken
                else ""
            )
        if col == 2:
            return _camera_key(photo.camera_make, photo.camera_model)
        if col == self._OUTPUT_COL:
            if self._resolver is None:
                return ""
            dest = self._resolver(photo)
            return str(dest) if dest is not None else ""
        return ""

    def setData(
        self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        """Handle checkbox toggles on the Name column."""
        if (
            role == Qt.ItemDataRole.CheckStateRole
            and index.isValid()
            and index.column() == self._NAME_COL
        ):
            self._checked[index.row()] = (
                Qt.CheckState(value) == Qt.CheckState.Checked
            )
            self.dataChanged.emit(
                index, index, [Qt.ItemDataRole.CheckStateRole]
            )
            return True
        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Return item flags; the Name column is user-checkable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == self._NAME_COL:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        """Return horizontal header labels."""
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return self.COLUMNS[section]
        return None


class FileFilterProxyModel(QSortFilterProxyModel):
    """Proxy that hides rows by extension and camera, leaving the model intact."""

    def __init__(self, parent=None):
        """Initialise with no filtering applied.

        Args:
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._allowed_exts: set[str] | None = None
        self._allowed_cams: set[str] | None = None

    def set_allowed(
        self, exts: set[str] | None, cams: set[str] | None
    ) -> None:
        """Restrict visible rows to the given extension and camera sets.

        Args:
            exts: Allowed lowercase extensions, or ``None`` to allow all.
            cams: Allowed camera keys, or ``None`` to allow all.
        """
        self._allowed_exts = exts
        self._allowed_cams = cams
        self.invalidate()

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        """Accept a row only when its extension and camera are both allowed."""
        model: FileTableModel = self.sourceModel()
        photo = model.photo_at(source_row)
        if self._allowed_exts is not None and photo.extension not in self._allowed_exts:
            return False
        if self._allowed_cams is not None:
            if _camera_key(photo.camera_make, photo.camera_model) not in self._allowed_cams:
                return False
        return True


class FileTableView(QWidget):
    """Scan-results table with selection checkboxes and an out-path preview.

    Wraps a :class:`FileTableModel` behind a :class:`FileFilterProxyModel` and
    adds a small toolbar (Select All / Select None over the *visible* rows) plus
    a live "*n* of *m* selected" label.

    Attributes:
        selection_changed: Emitted whenever the set of checked rows changes.
    """

    selection_changed = Signal()

    def __init__(self, parent=None):
        """Initialise an empty table view.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._model = FileTableModel()
        self._proxy = FileFilterProxyModel()
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setAlternatingRowColors(True)
        # Breathing room so cell text isn't flush against the column edges. With
        # ResizeToContents columns (Date/Camera) the style folds this padding
        # into the computed width, widening the column rather than clipping.
        self._table.setStyleSheet(
            "QTableView::item { padding-left: 6px; padding-right: 6px; }"
        )
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 220)

        self._select_all_btn = QPushButton("Select All")
        self._select_none_btn = QPushButton("Select None")
        self._count_label = QLabel("0 of 0 selected")

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._select_all_btn)
        toolbar.addWidget(self._select_none_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._count_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self._table, stretch=1)

        self._select_all_btn.clicked.connect(lambda: self._set_visible_checked(True))
        self._select_none_btn.clicked.connect(lambda: self._set_visible_checked(False))
        self._model.dataChanged.connect(self._on_model_changed)
        self._model.modelReset.connect(self._on_model_changed)

        self._update_count_label()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_files(self, files: Iterable[PhotoFile]) -> None:
        """Populate the table with scanned files (all checked)."""
        self._model.set_files(files)

    def set_resolver(self, resolver: DestResolver | None) -> None:
        """Set the Output Path resolver callback."""
        self._model.set_resolver(resolver)

    def refresh_output(self) -> None:
        """Recompute and repaint the Output Path column."""
        self._model.refresh_output()

    def set_filter(self, exts: set[str] | None, cams: set[str] | None) -> None:
        """Restrict visible rows to the given extension and camera sets."""
        self._proxy.set_allowed(exts, cams)
        self._update_count_label()

    def checked_visible_files(self) -> list[PhotoFile]:
        """Return checked files that also pass the current filter.

        The returned list follows the proxy's (possibly sorted) row order.
        """
        out: list[PhotoFile] = []
        for proxy_row in range(self._proxy.rowCount()):
            src = self._proxy.mapToSource(self._proxy.index(proxy_row, 0))
            if self._model.is_checked(src.row()):
                out.append(self._model.photo_at(src.row()))
        return out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_visible_checked(self, checked: bool) -> None:
        rows = [
            self._proxy.mapToSource(self._proxy.index(r, 0)).row()
            for r in range(self._proxy.rowCount())
        ]
        self._model.set_checked_for_rows(rows, checked)

    def _on_model_changed(self, *args) -> None:
        self._update_count_label()
        self.selection_changed.emit()

    def _update_count_label(self) -> None:
        checked = self._model.checked_count()
        total = self._model.rowCount()
        visible = self._proxy.rowCount()
        text = f"{checked} of {total} selected"
        if visible != total:
            text += f"  ({visible} shown)"
        self._count_label.setText(text)
