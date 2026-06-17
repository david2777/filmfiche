"""Drag-and-drop / browse widget for adding image files or a folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.core.tagger import TAG_EXTS


def collect_image_paths(paths: list) -> list[Path]:
    """Expand a mix of files and folders into supported image paths.

    Folders are listed non-recursively (mirroring ``analog_import``'s flat
    per-reel layout). The combined result — folder contents plus loose files — is
    sorted by filename (case-insensitive) ascending, so frames import in a
    predictable order. Anything without a supported extension is dropped.

    Args:
        paths: File/folder paths as ``str`` or ``Path``.

    Returns:
        Supported image paths, sorted by filename ascending.
    """
    out: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(c for c in path.iterdir() if c.suffix.lower() in TAG_EXTS)
        elif path.suffix.lower() in TAG_EXTS:
            out.append(path)
    out.sort(key=lambda p: p.name.lower())
    return out


class DropArea(QFrame):
    """A dashed drop target with Browse Files / Browse Folder buttons.

    Attributes:
        paths_added: Emitted with a ``list[Path]`` of supported images whenever
            files or a folder are dropped or browsed.
    """

    paths_added = Signal(list)

    def __init__(self, parent=None):
        """Initialise the drop area.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("DropArea")
        self.setStyleSheet(
            "#DropArea { border: 2px dashed palette(mid); border-radius: 6px; }"
        )

        prompt = QLabel("Drag images or a folder here")
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._browse_files_btn = QPushButton("Browse Files…")
        self._browse_folder_btn = QPushButton("Browse Folder…")
        self._browse_files_btn.clicked.connect(self._browse_files)
        self._browse_folder_btn.clicked.connect(self._browse_folder)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self._browse_files_btn)
        buttons.addWidget(self._browse_folder_btn)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(prompt)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, paths: list) -> None:
        images = collect_image_paths(paths)
        if images:
            self.paths_added.emit(images)

    def _browse_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, "Select Images", "", "Images (*.jpg *.jpeg *.tif *.tiff)"
        )
        if names:
            self._emit(names)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self._emit([folder])

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept the drag when it carries file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Collect supported images from the dropped URLs and emit them."""
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self._emit(paths)
