"""Template editor widget with presets, live preview, and validation."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.template import PRESETS, render_preview, validate_template


class TemplateEditor(QWidget):
    """Directory template editor with preset selector and live validation.

    Shows a preset combo, a free-form text field, a sample preview, and a
    colour-coded status line (red = error, amber = warning, green = valid).

    Attributes:
        template_changed: Emitted with the current template string on every
            change, regardless of validity.
    """

    template_changed = Signal(str)

    def __init__(self, parent=None):
        """Initialise with the first preset selected.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._line_edit = QLineEdit()
        self._line_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._preview_label = QLabel()
        self._status_label = QLabel()

        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Template:"))
        template_row.addWidget(self._line_edit, stretch=1)
        template_row.addWidget(self._status_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(template_row)
        layout.addWidget(self._preview_label)

        self._line_edit.customContextMenuRequested.connect(self._show_preset_menu)
        self._line_edit.textChanged.connect(self._on_text_changed)

        # Seed the line edit with the first preset (triggers _on_text_changed).
        self._line_edit.setText(PRESETS[0])

    @property
    def template(self) -> str:
        """Current text in the template line edit."""
        return self._line_edit.text()

    @property
    def is_valid(self) -> bool:
        """``True`` when :func:`validate_template` reports no errors."""
        return validate_template(self._line_edit.text()).is_valid

    def _show_preset_menu(self, pos) -> None:
        menu = self._line_edit.createStandardContextMenu()
        menu.addSeparator()
        for preset in PRESETS:
            menu.addAction(preset, lambda p=preset: self._line_edit.setText(p))
        menu.exec(self._line_edit.mapToGlobal(pos))

    def _on_text_changed(self, text: str) -> None:
        result = validate_template(text)
        preview = render_preview(text)

        self._preview_label.setText(preview)

        if result.errors:
            self._status_label.setText("Error: " + "; ".join(result.errors))
            self._status_label.setStyleSheet("color: red;")
        elif result.warnings:
            self._status_label.setText("Warning: " + "; ".join(result.warnings))
            self._status_label.setStyleSheet("color: orange;")
        else:
            self._status_label.setText("\u2713 Valid")
            self._status_label.setStyleSheet("color: green;")

        self.template_changed.emit(text)
