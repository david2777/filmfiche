"""Half Frame Splitter window.

A self-contained :class:`QDialog` that batch-splits a folder of half-frame scans
into individual ``-a`` (left) / ``-b`` (right) photos. The image work lives in
:mod:`app.core.half_frame`; this module is the GUI plus a background worker
following the ``progress``/``finished``/``error`` Signal pattern used elsewhere
(e.g. :class:`~app.gui.tagger_dialog.ExportWorker`).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from app.core.half_frame import SUPPORTED_EXTS, process_file
from app.gui.widgets.dir_picker import DirPicker
from app.models.split_result import SplitResult


class SplitWorker(QThread):
    """Splits every supported scan in a folder, off the GUI thread.

    Attributes:
        progress: Emitted after each file with ``(current, total)``.
        finished: Emitted with the completed :class:`~app.models.split_result.SplitResult`.
        error: Emitted with a human-readable message on a fatal failure.
    """

    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        input_dir: Path,
        output_dir: Path,
        mode: str,
        search_frac: float,
        gap: int,
        parent=None,
    ):
        """Initialise the worker.

        Args:
            input_dir: Folder of scans to read (non-recursive).
            output_dir: Folder to write the split photos into.
            mode: ``"auto"`` (detect seam) or ``"center"`` (split at the middle).
            search_frac: Central search window for ``"auto"`` detection.
            gap: Pixels to drop on each side of the seam.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._input_dir = input_dir
        self._output_dir = output_dir
        self._mode = mode
        self._search_frac = search_frac
        self._gap = gap

    def run(self) -> None:
        """Split each scan, accumulating a :class:`SplitResult`."""
        try:
            files = sorted(
                (p for p in self._input_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXTS),
                key=lambda p: p.name.lower(),
            )
            result = SplitResult()
            total = len(files)
            for i, src in enumerate(files, 1):
                try:
                    process_file(
                        src,
                        self._output_dir,
                        mode=self._mode,
                        search_frac=self._search_frac,
                        gap=self._gap,
                    )
                    result.processed += 1
                    result.written += 2
                except Exception as e:
                    result.errors += 1
                    result.messages.append(f"{src.name}: {e}")
                self.progress.emit(i, total)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class HalfFrameDialog(QDialog):
    """Folder-in / folder-out half-frame splitter with a few tuning controls."""

    def __init__(self, parent=None):
        """Build the splitter window.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Half Frame Splitter")
        self.resize(640, 280)
        self.setSizeGripEnabled(True)

        self._worker: SplitWorker | None = None

        self._input_picker = DirPicker("Input:")
        self._output_picker = DirPicker("Output:")

        folders_group = QGroupBox("Folders")
        folders_layout = QVBoxLayout(folders_group)
        folders_layout.addWidget(self._input_picker)
        folders_layout.addWidget(self._output_picker)

        # Detection mode.
        self._auto_radio = QRadioButton("Auto (detect seam)")
        self._center_radio = QRadioButton("Center")
        self._auto_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._auto_radio)
        mode_group.addButton(self._center_radio)

        # Tuning.
        self._search_spin = QSpinBox()
        self._search_spin.setRange(5, 90)
        self._search_spin.setValue(30)
        self._search_spin.setSuffix(" %")
        self._search_spin.setToolTip("Central fraction of the width searched for the seam (Auto mode).")
        self._gap_spin = QSpinBox()
        self._gap_spin.setRange(0, 500)
        self._gap_spin.setValue(0)
        self._gap_spin.setSuffix(" px")
        self._gap_spin.setToolTip("Pixels dropped on each side of the seam before cropping.")

        options_row = QHBoxLayout()
        options_row.addWidget(self._auto_radio)
        options_row.addWidget(self._center_radio)
        options_row.addSpacing(16)
        options_row.addWidget(QLabel("Search window"))
        options_row.addWidget(self._search_spin)
        options_row.addSpacing(8)
        options_row.addWidget(QLabel("Gap"))
        options_row.addWidget(self._gap_spin)
        options_row.addSpacing(16)
        options_row.addWidget(QLabel("Output: 3:4"))
        options_row.addStretch()

        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        options_layout.addLayout(options_row)

        self._split_btn = QPushButton("Split")
        self._split_btn.setEnabled(False)
        self._progress = QProgressBar()
        self._progress.setValue(0)
        self._status = QLabel("Select input and output folders to begin.")

        bottom = QHBoxLayout()
        bottom.addWidget(self._progress, stretch=1)
        bottom.addWidget(self._split_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(folders_group)
        layout.addWidget(options_group)
        layout.addLayout(bottom)
        layout.addWidget(self._status)

        self._input_picker.path_changed.connect(self._on_paths_changed)
        self._output_picker.path_changed.connect(self._on_paths_changed)
        self._auto_radio.toggled.connect(self._update_search_enabled)
        self._split_btn.clicked.connect(self._on_split)

        self._load_settings()
        self._update_search_enabled()
        self._update_split_enabled()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_paths_changed(self, _path: Path) -> None:
        self._update_split_enabled()
        self._save_settings()

    def _update_search_enabled(self) -> None:
        self._search_spin.setEnabled(self._auto_radio.isChecked())

    def _update_split_enabled(self) -> None:
        self._split_btn.setEnabled(
            self._input_picker.path is not None and self._output_picker.path is not None
        )

    def _on_split(self) -> None:
        input_dir = self._input_picker.path
        output_dir = self._output_picker.path
        if input_dir is None or output_dir is None:
            return

        self._save_settings()
        self._split_btn.setEnabled(False)
        self._progress.setValue(0)
        self._status.setText("Splitting…")

        self._worker = SplitWorker(
            input_dir,
            output_dir,
            mode="auto" if self._auto_radio.isChecked() else "center",
            search_frac=self._search_spin.value() / 100.0,
            gap=self._gap_spin.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress.setMaximum(total if total > 0 else 0)
        self._progress.setValue(current)

    def _on_finished(self, result: SplitResult) -> None:
        self._update_split_enabled()
        if result.processed == 0 and result.errors == 0:
            self._status.setText("No supported scans found in the input folder.")
            return
        status = (
            f"Split {result.processed} scan(s) → {result.written} photo(s)"
        )
        if result.errors:
            status += f"  ({result.errors} error(s))"
        self._status.setText(status)

    def _on_error(self, msg: str) -> None:
        self._update_split_enabled()
        self._status.setText(f"Error: {msg}")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings(self) -> None:
        s = QSettings()
        in_path = s.value("halfframe/input", "")
        if in_path:
            self._input_picker.set_directory(Path(in_path))
        out_path = s.value("halfframe/output", "")
        if out_path:
            self._output_picker.set_directory(Path(out_path))
        mode = s.value("halfframe/mode", "auto")
        self._center_radio.setChecked(mode == "center")
        self._auto_radio.setChecked(mode != "center")
        self._search_spin.setValue(int(s.value("halfframe/search", 30)))
        self._gap_spin.setValue(int(s.value("halfframe/gap", 0)))

    def _save_settings(self) -> None:
        s = QSettings()
        if path := self._input_picker.path:
            s.setValue("halfframe/input", str(path))
        if path := self._output_picker.path:
            s.setValue("halfframe/output", str(path))
        s.setValue("halfframe/mode", "auto" if self._auto_radio.isChecked() else "center")
        s.setValue("halfframe/search", self._search_spin.value())
        s.setValue("halfframe/gap", self._gap_spin.value())

    def closeEvent(self, event) -> None:
        """Persist settings and wait for a running split before closing."""
        if self._worker is not None:
            self._worker.wait(5000)
        self._save_settings()
        super().closeEvent(event)
