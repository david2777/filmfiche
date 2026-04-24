"""Step 2 UI tab: output directory, template, collision mode, filter, and move/copy."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.mover import CollisionMode, move_files
from app.core.scanner import _camera_key
from app.gui.widgets.dir_picker import DirPicker
from app.gui.widgets.filter_panel import FilterPanel
from app.gui.widgets.template_editor import TemplateEditor
from app.models.move_result import MoveResult
from app.models.photo_file import PhotoFile
from app.models.scan_result import ScanResult


class MoveWorker(QThread):
    """Background worker that runs :func:`~app.core.mover.move_files`.

    Attributes:
        progress: Emitted after each file with (current, total) counts.
        finished: Emitted with the completed :class:`~app.models.move_result.MoveResult`.
        error: Emitted with a human-readable message if an exception occurs.
    """

    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        files: list[PhotoFile],
        output_dir: Path,
        template: str,
        collision_mode: CollisionMode,
        source: Path,
        copy: bool = True,
        parent=None,
    ):
        """Initialise the worker.

        Args:
            files: Files to copy or move.
            output_dir: Root destination directory.
            template: Directory template string.
            collision_mode: How to handle pre-existing destination files.
            source: Original source root for ``_unknown/`` sub-paths.
            copy: ``True`` to copy (preserve source), ``False`` to move.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._files = files
        self._output_dir = output_dir
        self._template = template
        self._collision_mode = collision_mode
        self._source = source
        self._copy = copy

    def run(self) -> None:
        """Execute the move/copy synchronously and emit results."""
        try:
            result = move_files(
                self._files,
                self._output_dir,
                self._template,
                self._collision_mode,
                self._source,
                self._copy,
                progress_callback=lambda c, t: self.progress.emit(c, t),
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


_COLLISION_MODES = [CollisionMode.SKIP, CollisionMode.SUFFIX, CollisionMode.OVERRIDE]


class MoveTab(QWidget):
    """Step 2 tab: configure and execute a copy or move operation.

    Disabled until :meth:`load_scan_result` is called with a completed scan.
    """

    def __init__(self, parent=None):
        """Initialise the move tab layout and widgets.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._dir_picker = DirPicker("Output:")
        self._template_editor = TemplateEditor()

        collision_row = QWidget()
        collision_layout = QHBoxLayout(collision_row)
        collision_layout.setContentsMargins(0, 0, 0, 0)
        self._collision_combo = QComboBox()
        self._collision_combo.addItems(["Skip", "Add suffix", "Overwrite"])
        self._copy_check = QCheckBox("Copy files (uncheck to move)")
        self._copy_check.setChecked(True)
        collision_layout.addWidget(QLabel("Collision:"))
        collision_layout.addWidget(self._collision_combo)
        collision_layout.addSpacing(16)
        collision_layout.addWidget(self._copy_check)
        collision_layout.addStretch()

        self._filter_panel = FilterPanel()

        self._move_btn = QPushButton("Copy")
        self._move_btn.setEnabled(False)

        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._summary_label = QLabel("")
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)

        self._scan_result: ScanResult | None = None
        self._source: Path | None = None
        self._worker: MoveWorker | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(self._dir_picker)
        layout.addWidget(self._template_editor)
        layout.addWidget(collision_row)
        layout.addWidget(self._filter_panel)
        layout.addWidget(self._move_btn)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._log_edit, stretch=1)

        self._copy_check.toggled.connect(self._on_copy_toggled)
        self._move_btn.clicked.connect(self._on_move_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_scan_result(self, source: Path, result: ScanResult) -> None:
        """Populate the filter panel and enable the move button.

        Args:
            source: The directory that was scanned.
            result: The completed scan result.
        """
        self._source = source
        self._scan_result = result
        self._filter_panel.populate(result)
        self._move_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collision_mode(self) -> CollisionMode:
        return _COLLISION_MODES[self._collision_combo.currentIndex()]

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_copy_toggled(self, checked: bool) -> None:
        self._move_btn.setText("Copy" if checked else "Move")

    def _on_move_clicked(self) -> None:
        output_dir = self._dir_picker.path
        if output_dir is None:
            self._log_edit.append("Please select an output directory.")
            return
        if not self._template_editor.is_valid:
            self._log_edit.append("Template is invalid. Fix it before proceeding.")
            return
        if self._scan_result is None:
            return

        exts = self._filter_panel.selected_extensions()
        cams = self._filter_panel.selected_cameras()
        files = [
            f
            for f in self._scan_result.files
            if f.extension in exts
            and _camera_key(f.camera_make, f.camera_model) in cams
        ]

        self._move_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._log_edit.clear()

        self._worker = MoveWorker(
            files,
            output_dir,
            self._template_editor.template,
            self._collision_mode(),
            self._source,
            self._copy_check.isChecked(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)

    def _on_finished(self, result: MoveResult) -> None:
        self._move_btn.setEnabled(True)
        self._summary_label.setText(
            f"Moved: {result.moved}  Skipped: {result.skipped}  Errors: {result.errors}"
        )
        for line in result.log:
            self._log_edit.append(line)

    def _on_error(self, msg: str) -> None:
        self._move_btn.setEnabled(True)
        self._log_edit.append(f"Error: {msg}")
