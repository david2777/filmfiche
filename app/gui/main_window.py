"""Top-level application window — single-page vertical layout."""

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.gui.half_frame_dialog import HalfFrameDialog
from app.gui.move_tab import MoveTab
from app.gui.scan_tab import ScanTab
from app.gui.tagger_dialog import TaggerDialog


class MainWindow(QMainWindow):
    """Top-level application window with a single-page vertical layout."""

    def __init__(self, parent=None):
        """Initialise the main window.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Filmfiche")
        self.setMinimumSize(800, 600)
        self.resize(1200, 900)

        self._scan_tab = ScanTab()
        self._move_tab = MoveTab()
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._status_label = QLabel("Ready.")
        self._tagger_dialog: TaggerDialog | None = None
        self._splitter_dialog: HalfFrameDialog | None = None

        self._build_menu()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._scan_tab)
        layout.addWidget(self._move_tab, stretch=1)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._status_label)
        self.setCentralWidget(central)

        self._scan_tab.scan_progress.connect(self._on_progress)
        self._scan_tab.scan_status.connect(self._status_label.setText)
        self._scan_tab.scan_complete.connect(self._on_scan_complete)
        self._move_tab.move_progress.connect(self._on_progress)
        self._move_tab.move_status.connect(self._status_label.setText)

    def _build_menu(self) -> None:
        """Add the menu bar with the Tools actions."""
        tools_menu = self.menuBar().addMenu("&Tools")
        tagger_action = QAction("Film Metadata Tagger…", self)
        tagger_action.triggered.connect(self._open_tagger)
        tools_menu.addAction(tagger_action)
        splitter_action = QAction("Half Frame Splitter…", self)
        splitter_action.triggered.connect(self._open_splitter)
        tools_menu.addAction(splitter_action)

    @Slot()
    def _open_tagger(self) -> None:
        """Open (or re-focus) the Film Metadata Tagger window."""
        if self._tagger_dialog is None:
            self._tagger_dialog = TaggerDialog(self)
        self._tagger_dialog.show()
        self._tagger_dialog.raise_()
        self._tagger_dialog.activateWindow()

    @Slot()
    def _open_splitter(self) -> None:
        """Open (or re-focus) the Half Frame Splitter window."""
        if self._splitter_dialog is None:
            self._splitter_dialog = HalfFrameDialog(self)
        self._splitter_dialog.show()
        self._splitter_dialog.raise_()
        self._splitter_dialog.activateWindow()

    @Slot(int, int)
    def _on_progress(self, current: int, total: int) -> None:
        """Update the shared progress bar.

        Args:
            current: Number of files processed so far.
            total: Total number of files. 0 triggers indeterminate mode.
        """
        self._progress_bar.setMaximum(total if total > 0 else 0)
        self._progress_bar.setValue(current)

    @Slot(Path, object)
    def _on_scan_complete(self, source: Path, result) -> None:
        """Populate the move section when a scan finishes.

        Args:
            source: The directory that was scanned.
            result: The completed ScanResult.
        """
        self._move_tab.load_scan_result(source, result)


