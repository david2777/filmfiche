"""Film Metadata Tagger window.

A self-contained :class:`QDialog` that lets the user load scanned frames, enter or
import metadata, and export tagged, renamed copies. EXIF assembly and writing live
in :mod:`app.core.tagger`; this module is the GUI plus two background workers that
follow the ``progress``/``finished``/``error`` Signal pattern used by
:class:`~app.gui.scan_tab.ScanWorker` and :class:`~app.gui.move_tab.MoveWorker`.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QDateTime, QSettings, QThread, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.core.tagger import build_exif, output_path, write_image
from app.gui.widgets.drop_area import DropArea
from app.gui.widgets.frame_table import EXIF_DT_FORMAT, FrameTable
from app.models.film_frame import FilmFrame, build_full_entry, frames_from_json

_THUMB_PX = 96


class ThumbnailWorker(QThread):
    """Loads downscaled thumbnails off the GUI thread.

    Attributes:
        ready: Emitted with ``(FilmFrame, QImage)`` for each loaded image. Keying
            on the frame (not a row index) keeps thumbnails correct across a
            reorder such as :meth:`~app.gui.widgets.frame_table.FrameTable.reverse_order`.
    """

    ready = Signal(object, object)

    def __init__(self, frames: list[FilmFrame], size: int = _THUMB_PX, parent=None):
        """Initialise the worker.

        Args:
            frames: Frames to load thumbnails for.
            size: Maximum thumbnail edge in pixels.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._frames = frames
        self._size = size

    def run(self) -> None:
        """Decode each frame's image to a small ``QImage`` and emit it."""
        for frame in self._frames:
            try:
                with Image.open(frame.source_path) as img:
                    try:
                        img.draft("RGB", (self._size, self._size))
                    except Exception:
                        pass  # draft is a JPEG speed-up; ignore where unsupported
                    img = img.convert("RGB")
                    img.thumbnail((self._size, self._size))
                    qimg = QImage(
                        img.tobytes("raw", "RGB"),
                        img.width,
                        img.height,
                        3 * img.width,
                        QImage.Format.Format_RGB888,
                    ).copy()  # detach from the soon-to-be-freed buffer
                self.ready.emit(frame, qimg)
            except Exception:
                continue


class ExportWorker(QThread):
    """Builds EXIF and writes every frame to the chosen export root.

    Attributes:
        progress: Emitted after each file with ``(current, total)``.
        finished: Emitted with the count of files written.
        error: Emitted with a human-readable message on failure.
    """

    progress = Signal(int, int)
    finished = Signal(int)
    error = Signal(str)

    def __init__(
        self,
        frames: list[FilmFrame],
        globals_dict: dict,
        export_root: Path,
        parent=None,
    ):
        """Initialise the worker.

        Args:
            frames: Frames to export, in order.
            globals_dict: Reel-wide metadata merged into every frame.
            export_root: Parent directory for the ``{reel}-{document}`` folder.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self._frames = frames
        self._globals = globals_dict
        self._root = export_root

    def run(self) -> None:
        """Tag and write every frame, emitting progress as it goes."""
        try:
            total = len(self._frames)
            written = 0
            for i, frame in enumerate(self._frames, 1):
                entry = build_full_entry(frame, self._globals)
                reel = entry.get("ReelName")
                if not reel:
                    raise ValueError("Reel Name is required.")
                document = entry.get("DocumentName") or "Unknown"
                number = entry.get("ImageNumber", i)
                exif_bytes = build_exif(entry)
                dst = output_path(
                    self._root, reel, document, number, frame.source_path.suffix
                )
                write_image(frame.source_path, dst, exif_bytes, entry)
                written += 1
                self.progress.emit(i, total)
            self.finished.emit(written)
        except Exception as e:
            self.error.emit(str(e))


class DateTimePickerDialog(QDialog):
    """Modal calendar / clock picker returning an EXIF-formatted datetime string."""

    def __init__(self, initial: QDateTime | None = None, parent=None):
        """Build the picker.

        Args:
            initial: Datetime to pre-select; defaults to *now* when ``None`` or
                invalid.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Set Date / Time")

        if initial is None or not initial.isValid():
            initial = QDateTime.currentDateTime()
        self._edit = QDateTimeEdit(initial)
        self._edit.setDisplayFormat(EXIF_DT_FORMAT)
        self._edit.setCalendarPopup(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Date / time to apply to the selected frame(s):"))
        layout.addWidget(self._edit)
        layout.addWidget(buttons)

    def value(self) -> str:
        """Return the chosen datetime as an EXIF ``YYYY:MM:DD HH:MM:SS`` string."""
        return self._edit.dateTime().toString(EXIF_DT_FORMAT)


class TaggerDialog(QDialog):
    """Drag-drop / browse → edit metadata → export tagged film scans."""

    def __init__(self, parent=None):
        """Build the tagger window.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Film Metadata Tagger")
        self.resize(1000, 760)
        self.setSizeGripEnabled(True)

        self._imported_globals: dict = {}
        self._thumb_workers: list[ThumbnailWorker] = []
        self._export_worker: ExportWorker | None = None

        self._drop = DropArea()

        self._make = QLineEdit()
        self._model = QLineEdit()
        self._reel = QLineEdit()
        self._doc = QLineEdit()
        self._film = QLineEdit()
        self._iso = QLineEdit()
        self._make.setPlaceholderText("e.g. Olympus")
        self._model.setPlaceholderText("e.g. OM-2n")
        self._reel.setPlaceholderText("e.g. 1003 (required)")
        self._doc.setPlaceholderText("e.g. Kodak Gold 200")
        self._film.setPlaceholderText("Film stock")
        self._iso.setPlaceholderText("e.g. 200")
        self._import_btn = QPushButton("Import JSON…")

        reel_group = QGroupBox("Reel / Camera")
        grid = QGridLayout(reel_group)
        grid.addWidget(QLabel("Make"), 0, 0)
        grid.addWidget(self._make, 0, 1)
        grid.addWidget(QLabel("Model"), 0, 2)
        grid.addWidget(self._model, 0, 3)
        grid.addWidget(QLabel("Reel Name"), 1, 0)
        grid.addWidget(self._reel, 1, 1)
        grid.addWidget(QLabel("Document"), 1, 2)
        grid.addWidget(self._doc, 1, 3)
        grid.addWidget(QLabel("Film"), 2, 0)
        grid.addWidget(self._film, 2, 1)
        grid.addWidget(QLabel("ISO"), 2, 2)
        grid.addWidget(self._iso, 2, 3)
        grid.addWidget(self._import_btn, 2, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self._reverse_btn = QPushButton("Reverse Order")
        self._reverse_btn.setToolTip(
            "Flip the frame sequence so the last file becomes #1.\n"
            "Use when the scan direction is the opposite of the metadata order."
        )
        self._reverse_btn.setEnabled(False)

        self._set_date_btn = QPushButton("Set Date for Selected…")
        self._set_date_btn.setToolTip(
            "Open a date/time picker and apply it to every selected frame."
        )
        self._set_date_btn.setEnabled(False)

        table_toolbar = QHBoxLayout()
        table_toolbar.addWidget(self._reverse_btn)
        table_toolbar.addWidget(self._set_date_btn)
        table_toolbar.addStretch()

        self._table = FrameTable()

        self._export_btn = QPushButton("Export…")
        self._export_btn.setEnabled(False)
        self._progress = QProgressBar()
        self._progress.setValue(0)
        self._status = QLabel("Add images to begin.")

        bottom = QHBoxLayout()
        bottom.addWidget(self._progress, stretch=1)
        bottom.addWidget(self._export_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self._drop)
        layout.addWidget(reel_group)
        layout.addLayout(table_toolbar)
        layout.addWidget(self._table, stretch=1)
        layout.addLayout(bottom)
        layout.addWidget(self._status)

        self._drop.paths_added.connect(self._add_paths)
        self._import_btn.clicked.connect(self._on_import_json)
        self._reverse_btn.clicked.connect(self._on_reverse)
        self._set_date_btn.clicked.connect(self._on_set_date)
        self._table.itemSelectionChanged.connect(self._update_set_date_enabled)
        self._export_btn.clicked.connect(self._on_export)
        self._reel.textChanged.connect(self._update_export_enabled)

        self._load_settings()
        self._update_export_enabled()

    # ------------------------------------------------------------------
    # Loading images
    # ------------------------------------------------------------------

    def _add_paths(self, paths: list) -> None:
        new_frames = [FilmFrame(source_path=Path(p)) for p in paths]
        self._table.add_frames(new_frames)
        self._start_thumbnails(new_frames)
        self._reverse_btn.setEnabled(bool(self._table.frames()))
        self._status.setText(f"{len(self._table.frames())} image(s) loaded.")
        self._update_export_enabled()

    def _start_thumbnails(self, frames: list[FilmFrame]) -> None:
        worker = ThumbnailWorker(frames)
        worker.ready.connect(self._table.set_thumbnail)
        worker.finished.connect(lambda w=worker: self._forget_worker(w))
        self._thumb_workers.append(worker)
        worker.start()

    def _on_reverse(self) -> None:
        self._table.reverse_order()
        count = len(self._table.frames())
        if count:
            self._status.setText(f"Reversed frame order ({count} frame(s)).")

    def _update_set_date_enabled(self) -> None:
        self._set_date_btn.setEnabled(bool(self._table.selected_frames()))

    def _on_set_date(self) -> None:
        selected = self._table.selected_frames()
        if not selected:
            self._status.setText("Select one or more frames first.")
            return
        existing = selected[0].entry.get("DateTimeOriginal")
        initial = (
            QDateTime.fromString(str(existing), EXIF_DT_FORMAT) if existing else None
        )
        dialog = DateTimePickerDialog(initial, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            count = self._table.set_datetime_for_selected(dialog.value())
            self._status.setText(f"Set date on {count} frame(s).")

    def _forget_worker(self, worker: ThumbnailWorker) -> None:
        if worker in self._thumb_workers:
            self._thumb_workers.remove(worker)

    # ------------------------------------------------------------------
    # JSON import
    # ------------------------------------------------------------------

    def _on_import_json(self) -> None:
        if not self._table.frames():
            self._status.setText("Add images before importing JSON.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Metadata JSON", "", "JSON (*.json)"
        )
        if path:
            self._apply_json(path)

    def _apply_json(self, path: str) -> None:
        """Read a JSON file and apply it to the loaded frames (paired by order)."""
        try:
            entries = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            self._status.setText(f"Could not read JSON: {e}")
            return
        try:
            globals_dict, _, warning = frames_from_json(entries, self._table.frames())
        except ValueError as e:
            self._status.setText(f"Invalid JSON: {e}")
            return

        self._imported_globals = globals_dict
        self._fill_globals_fields(globals_dict)
        self._table.refresh()
        self._status.setText(warning or "Imported metadata from JSON.")
        self._update_export_enabled()

    def _fill_globals_fields(self, g: dict) -> None:
        self._make.setText(str(g.get("Make", "")))
        self._model.setText(str(g.get("Model", "")))
        self._reel.setText(str(g.get("ReelName", "")))
        self._doc.setText(str(g.get("DocumentName", "")))
        self._film.setText(str(g.get("SpectralSensitivity") or g.get("DocumentName") or ""))
        self._iso.setText(str(g.get("ISO") or g.get("ISOSpeed") or ""))

    # ------------------------------------------------------------------
    # Globals
    # ------------------------------------------------------------------

    def _collect_globals(self) -> dict:
        """Merge imported reel globals with the current visible field values."""
        g = dict(self._imported_globals)

        def setf(key: str, widget: QLineEdit) -> None:
            text = widget.text().strip()
            if text:
                g[key] = text
            else:
                g.pop(key, None)

        setf("Make", self._make)
        setf("Model", self._model)
        setf("ReelName", self._reel)
        setf("DocumentName", self._doc)

        film = self._film.text().strip()
        if film:
            g["SpectralSensitivity"] = film
            g.setdefault("Description", film)

        iso = self._iso.text().strip()
        if iso:
            g["ISO"] = iso
            g["ISOSpeed"] = iso
        else:
            g.pop("ISO", None)
            g.pop("ISOSpeed", None)

        return g

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _on_export(self) -> None:
        frames = self._table.frames()
        if not frames:
            self._status.setText("No images to export.")
            return
        g = self._collect_globals()
        if not g.get("ReelName"):
            self._status.setText("Enter a Reel Name before exporting.")
            return
        root = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not root:
            return

        self._save_settings()
        self._export_btn.setEnabled(False)
        self._progress.setMaximum(len(frames))
        self._progress.setValue(0)
        self._status.setText("Exporting…")

        self._export_worker = ExportWorker(frames, g, Path(root))
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_progress(self, current: int, total: int) -> None:
        self._progress.setMaximum(total if total > 0 else 0)
        self._progress.setValue(current)

    def _on_export_finished(self, count: int) -> None:
        self._export_btn.setEnabled(True)
        self._status.setText(f"Exported {count} file(s).")

    def _on_export_error(self, msg: str) -> None:
        self._export_btn.setEnabled(True)
        self._status.setText(f"Error: {msg}")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _update_export_enabled(self) -> None:
        self._export_btn.setEnabled(
            bool(self._table.frames()) and bool(self._reel.text().strip())
        )

    def _load_settings(self) -> None:
        s = QSettings()
        self._make.setText(s.value("tagger/make", ""))
        self._model.setText(s.value("tagger/model", ""))
        self._film.setText(s.value("tagger/film", ""))
        self._iso.setText(s.value("tagger/iso", ""))

    def _save_settings(self) -> None:
        s = QSettings()
        s.setValue("tagger/make", self._make.text())
        s.setValue("tagger/model", self._model.text())
        s.setValue("tagger/film", self._film.text())
        s.setValue("tagger/iso", self._iso.text())

    def closeEvent(self, event) -> None:
        """Persist defaults and wait for running workers before closing."""
        for worker in list(self._thumb_workers):
            worker.wait(2000)
        if self._export_worker is not None:
            self._export_worker.wait(5000)
        self._save_settings()
        super().closeEvent(event)
