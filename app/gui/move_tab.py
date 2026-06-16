"""Step 2 UI tab: output directory, template, collision mode, filter, and move/copy."""

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.core.mover import CollisionMode, move_files, resolve_dest
from app.gui.widgets.dir_picker import DirPicker
from app.gui.widgets.file_table import FileTableView
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
        default_make: str = "",
        default_model: str = "",
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
            default_make: Fallback camera make for files without camera metadata.
            default_model: Fallback camera model for files without camera metadata.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._files = files
        self._output_dir = output_dir
        self._template = template
        self._collision_mode = collision_mode
        self._source = source
        self._copy = copy
        self._default_make = default_make
        self._default_model = default_model

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
                default_make=self._default_make,
                default_model=self._default_model,
            )
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MoveTab(QWidget):
    """Step 2 tab: configure and execute a copy or move operation.

    Disabled until :meth:`load_scan_result` is called with a completed scan.
    """

    move_progress = Signal(int, int)
    move_status = Signal(str)

    def __init__(self, parent=None):
        """Initialise the move tab layout and widgets.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._dir_picker = DirPicker("Output:")
        self._template_editor = TemplateEditor()

        # Mode radio buttons (Copy / Move)
        self._copy_radio = QRadioButton("Copy")
        self._move_radio = QRadioButton("Move")
        self._copy_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._copy_radio)
        mode_group.addButton(self._move_radio)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode"))
        mode_row.addWidget(self._copy_radio)
        mode_row.addWidget(self._move_radio)
        mode_row.addStretch()

        # Collision radio buttons (Skip / Add Suffix / Overwrite)
        self._skip_radio = QRadioButton("Skip")
        self._suffix_radio = QRadioButton("Add Suffix")
        self._override_radio = QRadioButton("Overwrite")
        self._skip_radio.setChecked(True)
        collision_group = QButtonGroup(self)
        collision_group.addButton(self._skip_radio)
        collision_group.addButton(self._suffix_radio)
        collision_group.addButton(self._override_radio)

        collision_row = QHBoxLayout()
        collision_row.addWidget(QLabel("Collision"))
        collision_row.addWidget(self._skip_radio)
        collision_row.addWidget(self._suffix_radio)
        collision_row.addWidget(self._override_radio)
        collision_row.addStretch()

        options_layout = QVBoxLayout()
        options_layout.addLayout(mode_row)
        options_layout.addLayout(collision_row)
        options_layout.addStretch()

        template_options_row = QHBoxLayout()
        template_options_row.addWidget(self._template_editor, stretch=1)
        template_options_row.addLayout(options_layout)

        self._default_make_edit = QLineEdit()
        self._default_make_edit.setPlaceholderText("Default make")
        self._default_model_edit = QLineEdit()
        self._default_model_edit.setPlaceholderText("Default model")

        camera_fallback_row = QHBoxLayout()
        camera_fallback_row.addWidget(QLabel("Default Make:"))
        camera_fallback_row.addWidget(self._default_make_edit, stretch=1)
        camera_fallback_row.addSpacing(12)
        camera_fallback_row.addWidget(QLabel("Default Model:"))
        camera_fallback_row.addWidget(self._default_model_edit, stretch=1)

        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        output_layout.addWidget(self._dir_picker)
        output_layout.addLayout(template_options_row)
        output_layout.addLayout(camera_fallback_row)

        self._filter_panel = FilterPanel()
        filters_group = QGroupBox("Filters")
        filters_layout = QVBoxLayout(filters_group)
        filters_layout.addWidget(self._filter_panel)

        self._move_btn = QPushButton("Copy")
        self._move_btn.setEnabled(False)

        self._file_table = FileTableView()

        self._scan_result: ScanResult | None = None
        self._source: Path | None = None
        self._worker: MoveWorker | None = None
        self._loading = False

        results_group = QGroupBox("Files")
        results_layout = QVBoxLayout(results_group)
        results_layout.addWidget(self._file_table)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(output_group)
        layout.addWidget(filters_group)
        layout.addWidget(results_group, stretch=1)
        layout.addWidget(self._move_btn)

        self.setEnabled(False)

        self._dir_picker.path_changed.connect(self._update_move_btn)
        self._dir_picker.path_changed.connect(self._save_settings)
        self._dir_picker.path_changed.connect(self._refresh_preview)
        self._template_editor.template_changed.connect(self._save_settings)
        self._template_editor.template_changed.connect(self._refresh_preview)
        self._copy_radio.toggled.connect(self._on_copy_toggled)
        self._copy_radio.toggled.connect(self._save_settings)
        self._skip_radio.toggled.connect(self._save_settings)
        self._suffix_radio.toggled.connect(self._save_settings)
        self._override_radio.toggled.connect(self._save_settings)
        self._default_make_edit.textChanged.connect(self._save_settings)
        self._default_make_edit.textChanged.connect(self._refresh_preview)
        self._default_model_edit.textChanged.connect(self._save_settings)
        self._default_model_edit.textChanged.connect(self._refresh_preview)
        self._filter_panel.filter_changed.connect(self._apply_filter)
        self._move_btn.clicked.connect(self._on_move_clicked)

        self._load_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_scan_result(self, source: Path, result: ScanResult) -> None:
        """Populate the filter panel and enable the move section.

        Args:
            source: The directory that was scanned.
            result: The completed scan result.
        """
        self.setEnabled(True)
        self._source = source
        self._scan_result = result
        self._filter_panel.populate(result)
        self._file_table.set_files(result.files)
        self._apply_filter()
        self._refresh_preview()
        self._update_move_btn()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_resolver(self):
        """Return a callable mapping a ``PhotoFile`` to its previewed dest path.

        The path is shown relative to the output directory when possible. Files
        already moved (``resolved_dest`` set) report their actual destination.
        Returns ``None`` when no output directory or source is available yet.
        """
        output = self._dir_picker.path
        source = self._source
        if output is None or source is None:
            return None
        template = self._template_editor.template
        make = self._default_make_edit.text().strip()
        model = self._default_model_edit.text().strip()

        def resolve(photo):
            try:
                dest = photo.resolved_dest or resolve_dest(
                    photo, output, template, source, make, model
                )
            except Exception:
                return None
            try:
                return dest.relative_to(output)
            except (ValueError, TypeError):
                return dest

        return resolve

    def _refresh_preview(self) -> None:
        """Rebuild the Output Path resolver and repaint that column."""
        self._file_table.set_resolver(self._build_resolver())

    def _apply_filter(self) -> None:
        """Push the filter panel's selections into the table's proxy filter."""
        if self._scan_result is None:
            return
        self._file_table.set_filter(
            self._filter_panel.selected_extensions(),
            self._filter_panel.selected_cameras(),
        )

    def _update_move_btn(self) -> None:
        """Enable the action button only when both scan and output path are set."""
        self._move_btn.setEnabled(
            self._scan_result is not None and self._dir_picker.path is not None
        )

    def _load_settings(self) -> None:
        """Restore persisted output settings from QSettings."""
        self._loading = True
        try:
            s = QSettings()
            path = s.value("output/path", "")
            if path:
                self._dir_picker.set_directory(Path(path))
            template = s.value("output/template", "")
            if template:
                self._template_editor._line_edit.setText(template)
            mode = s.value("output/mode", "copy")
            self._copy_radio.setChecked(mode == "copy")
            self._move_radio.setChecked(mode == "move")
            collision = s.value("output/collision", "skip")
            self._suffix_radio.setChecked(collision == "suffix")
            self._override_radio.setChecked(collision == "override")
            self._skip_radio.setChecked(collision not in ("suffix", "override"))
            self._default_make_edit.setText(s.value("output/default_make", ""))
            self._default_model_edit.setText(s.value("output/default_model", ""))
        finally:
            self._loading = False
        self._update_move_btn()

    def _save_settings(self) -> None:
        """Persist current output settings to QSettings."""
        if self._loading:
            return
        s = QSettings()
        path = self._dir_picker.path
        if path:
            s.setValue("output/path", str(path))
        s.setValue("output/template", self._template_editor.template)
        s.setValue("output/mode", "copy" if self._copy_radio.isChecked() else "move")
        if self._suffix_radio.isChecked():
            s.setValue("output/collision", "suffix")
        elif self._override_radio.isChecked():
            s.setValue("output/collision", "override")
        else:
            s.setValue("output/collision", "skip")
        s.setValue("output/default_make", self._default_make_edit.text())
        s.setValue("output/default_model", self._default_model_edit.text())

    def _collision_mode(self) -> CollisionMode:
        if self._suffix_radio.isChecked():
            return CollisionMode.SUFFIX
        if self._override_radio.isChecked():
            return CollisionMode.OVERRIDE
        return CollisionMode.SKIP

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_copy_toggled(self, checked: bool) -> None:
        self._move_btn.setText("Copy" if checked else "Move")

    def _on_move_clicked(self) -> None:
        output_dir = self._dir_picker.path
        if not self._template_editor.is_valid:
            self.move_status.emit("Template is invalid. Fix it before proceeding.")
            return
        if self._scan_result is None:
            return

        files = self._file_table.checked_visible_files()
        if not files:
            self.move_status.emit("No files selected.")
            return

        if not self._confirm_hidden_selection(len(files)):
            return

        self._move_btn.setEnabled(False)
        self.move_progress.emit(0, 0)

        self._worker = MoveWorker(
            files,
            output_dir,
            self._template_editor.template,
            self._collision_mode(),
            self._source,
            self._copy_radio.isChecked(),
            default_make=self._default_make_edit.text().strip(),
            default_model=self._default_model_edit.text().strip(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _confirm_hidden_selection(self, visible_count: int) -> bool:
        """Confirm before acting when checked files are hidden by the filter.

        Args:
            visible_count: Number of checked, filter-visible files that will move.

        Returns:
            ``True`` to proceed, ``False`` if the user cancels. Returns ``True``
            immediately when no checked files are hidden.
        """
        hidden = self._file_table.hidden_selected_count()
        if hidden <= 0:
            return True

        copying = self._copy_radio.isChecked()
        action = "Copy" if copying else "Move"
        action_past = "copied" if copying else "moved"
        h_noun, h_verb = ("file", "is") if hidden == 1 else ("files", "are")
        v_noun = "file" if visible_count == 1 else "files"

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(f"{action} fewer files than selected")
        box.setText(
            f"{hidden} selected {h_noun} {h_verb} hidden by the current filter "
            f"and won't be {action_past}."
        )
        box.setInformativeText(f"Continue with the {visible_count} visible {v_noun}?")
        proceed_btn = box.addButton(
            f"{action} {visible_count} {v_noun}", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(proceed_btn)
        box.exec()
        return box.clickedButton() is proceed_btn

    def _on_progress(self, current: int, total: int) -> None:
        self.move_progress.emit(current, total)

    def _on_finished(self, result: MoveResult) -> None:
        self._update_move_btn()
        status = f"Moved: {result.moved}  Skipped: {result.skipped}  Errors: {result.errors}"
        if result.mtime_used:
            status += f"  ({result.mtime_used} using mtime)"
        self.move_status.emit(status)
        # Reflect the actual destinations (with any collision suffix) now set on
        # the moved PhotoFile objects.
        self._refresh_preview()

    def _on_error(self, msg: str) -> None:
        self._update_move_btn()
        self.move_status.emit(f"Error: {msg}")
