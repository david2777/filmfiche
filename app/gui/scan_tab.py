"""Step 1 UI tab: source directory picker, Scan button, progress, and summary."""

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QThread

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

    def __init__(self, parent=None):
        """Initialise the scan tab layout and widgets.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._dir_picker = DirPicker("Source:")
        self._scan_btn = QPushButton("Scan")
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._status_label = QLabel("Ready.")
        self._worker: ScanWorker | None = None

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._scan_btn)
        btn_row.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(self._dir_picker)
        layout.addLayout(btn_row)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._status_label)
        layout.addStretch()

        self._scan_btn.clicked.connect(self._on_scan_clicked)

    @property
    def source_path(self) -> Path | None:
        """Current source directory, or ``None`` if none has been selected."""
        return self._dir_picker.path

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_scan_clicked(self) -> None:
        if self.source_path is None:
            self._status_label.setText("Please select a source directory first.")
            return
        self._scan_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._status_label.setText("Scanning…")

        self._worker = ScanWorker(self.source_path)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)
        self._status_label.setText(f"Scanning… {current}/{total}")

    def _on_finished(self, result: ScanResult) -> None:
        self._scan_btn.setEnabled(True)
        no_date = sum(1 for f in result.files if f.date_taken is None)
        total = len(result.files)
        self._status_label.setText(
            f"{total} file(s) found"
            + (f" ({no_date} without date)" if no_date else "")
        )
        self.scan_complete.emit(self.source_path, result)

    def _on_error(self, msg: str) -> None:
        self._scan_btn.setEnabled(True)
        self._status_label.setText(f"Error: {msg}")
