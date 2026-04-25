"""Labeled directory picker widget."""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class DirPicker(QWidget):
    """A row widget: label + read-only line edit + Browse button.

    Attributes:
        path_changed: Emitted with the new ``Path`` whenever a valid directory
            is chosen or set programmatically.
    """

    path_changed = Signal(Path)

    def __init__(self, label: str = "Directory", parent=None):
        """Initialise the picker.

        Args:
            label: Text shown in the ``QLabel`` to the left of the path field.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._line_edit = QLineEdit()
        self._line_edit.setReadOnly(True)
        self._line_edit.setPlaceholderText("No directory selected")

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        layout.addWidget(self._line_edit, stretch=1)
        layout.addWidget(browse_btn)

    @property
    def path(self) -> Path | None:
        """Current directory as ``Path``, or ``None`` if the field is empty."""
        text = self._line_edit.text().strip()
        return Path(text) if text else None

    def set_directory(self, path: Path) -> None:
        """Set the displayed path and emit :attr:`path_changed`.

        Args:
            path: The directory path to display.
        """
        self._line_edit.setText(path.as_posix())
        self.path_changed.emit(path)

    def _on_browse(self):
        chosen = QFileDialog.getExistingDirectory(self, "Select Directory")
        if chosen:
            self.set_directory(Path(chosen))
