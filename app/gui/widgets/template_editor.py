"""Template editor widget with presets, live preview, and validation."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
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

        self._preset_combo = QComboBox()
        self._preset_combo.addItems(PRESETS)
        self._preset_combo.addItem("(custom)")

        self._line_edit = QLineEdit()
        self._preview_label = QLabel()
        self._status_label = QLabel()

        layout = QFormLayout(self)
        layout.addRow("Preset:", self._preset_combo)
        layout.addRow("Template:", self._line_edit)
        layout.addRow("Preview:", self._preview_label)
        layout.addRow("Status:", self._status_label)

        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
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

    def _on_preset_selected(self, index: int) -> None:
        if index < len(PRESETS):
            self._line_edit.setText(PRESETS[index])

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
