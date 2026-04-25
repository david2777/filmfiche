"""Step 1 UI: source directory picker and Scan button."""

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.scanner import scan_directory
from app.gui.widgets.dir_picker import DirPicker
from app.models.scan_result import ScanResult


class ScanWorker(QThread):
    """Background worker that runs :func:`~app.core.scanner.scan_directory`.

    Attributes:
        progress: Emitted after each file with (current, total) counts.
        finished: Emitted with the completed :class:`~app.models.scan_result.ScanResult`.
        error: Emitted with a human-readable message if an exception occurs.
    """

    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, source: Path, parent=None):
        """Initialise the worker.

        Args:
            source: Directory to scan.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._source = source

    def run(self) -> None:
        """Execute the scan synchronously and emit results."""
        try:
            result = scan_directory(
                self._source,
                progress_callback=lambda c, t: self.progress.emit(c, t),
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class ScanTab(QWidget):
    """Step 1 tab: lets the user pick a source folder and run a scan.

    Attributes:
        scan_complete: Emitted with ``(source_path, ScanResult)`` when the scan
            finishes successfully.
    """

    scan_complete = Signal(Path, object)
    scan_progress = Signal(int, int)
    scan_status = Signal(str)

    def __init__(self, parent=None):
        """Initialise the scan tab layout and widgets.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._dir_picker = DirPicker("Source:")
        self._scan_btn = QPushButton("Scan")
        self._worker: ScanWorker | None = None

        source_group = QGroupBox("Source")
        group_layout = QVBoxLayout(source_group)
        group_layout.addWidget(self._dir_picker)
        group_layout.addWidget(self._scan_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(source_group)

        self._dir_picker.path_changed.connect(self._save_settings)
        self._scan_btn.clicked.connect(self._on_scan_clicked)

        self._load_settings()

    def _load_settings(self) -> None:
        path = QSettings().value("source/path", "")
        if path:
            self._dir_picker.set_directory(Path(path))

    def _save_settings(self) -> None:
        path = self._dir_picker.path
        if path:
            QSettings().setValue("source/path", str(path))

    @property
    def source_path(self) -> Path | None:
        """Current source directory, or ``None`` if none has been selected."""
        return self._dir_picker.path

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_scan_clicked(self) -> None:
        if self.source_path is None:
            self.scan_status.emit("Please select a source directory first.")
            return
        self._scan_btn.setEnabled(False)
        self.scan_progress.emit(0, 0)
        self.scan_status.emit("Scanning…")

        self._worker = ScanWorker(self.source_path)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self.scan_progress.emit(current, total)
        self.scan_status.emit(f"Scanning… {current}/{total}")

    def _on_finished(self, result: ScanResult) -> None:
        self._scan_btn.setEnabled(True)
        no_date = sum(1 for f in result.files if f.date_taken is None)
        total = len(result.files)
        self.scan_status.emit(
            f"{total} file(s) found"
            + (f" ({no_date} without date)" if no_date else "")
        )
        self.scan_complete.emit(self.source_path, result)

    def _on_error(self, msg: str) -> None:
        self._scan_btn.setEnabled(True)
        self.scan_status.emit(f"Error: {msg}")
