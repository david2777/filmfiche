"""Top-level application window — single-page vertical layout."""

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.gui.move_tab import MoveTab
from app.gui.scan_tab import ScanTab


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


