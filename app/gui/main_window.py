"""Top-level application window with a two-tab layout."""

from pathlib import Path

from PySide6.QtWidgets import QMainWindow, QTabWidget

from app.gui.move_tab import MoveTab
from app.gui.scan_tab import ScanTab
from app.models.scan_result import ScanResult


class MainWindow(QMainWindow):
    """Top-level application window with a two-tab layout."""

    def __init__(self, parent=None):
        """Initialise the main window, tabs, and menu bar.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Filmfiche")
        self.setMinimumSize(800, 600)

        self._scan_tab = ScanTab()
        self._move_tab = MoveTab()

        self._tabs = QTabWidget()
        self._tabs.addTab(self._scan_tab, "1 · Scan")
        self._tabs.addTab(self._move_tab, "2 · Move / Copy")
        self.setCentralWidget(self._tabs)

        self._build_menu()

        self._scan_tab.scan_complete.connect(self._on_scan_complete)

    def _build_menu(self) -> None:
        """Build the application menu bar."""
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("E&xit", self.close)

    def _on_scan_complete(self, source: Path, result: ScanResult) -> None:
        """Populate the move tab and switch to it.

        Args:
            source: The directory that was scanned.
            result: The completed scan result.
        """
        self._move_tab.load_scan_result(source, result)
        self._tabs.setCurrentWidget(self._move_tab)
