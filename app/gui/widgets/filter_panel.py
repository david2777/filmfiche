"""Extension and camera filter panel widget."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from app.models.scan_result import ScanResult


class FilterPanel(QWidget):
    """Two-column filter panel with Extensions and Cameras group boxes.

    Each group box contains one :class:`QCheckBox` per entry, all pre-checked.
    Toggling any checkbox emits :attr:`filter_changed`.

    Attributes:
        filter_changed: Emitted whenever any checkbox is toggled.
    """

    filter_changed = Signal()

    def __init__(self, parent=None):
        """Initialise an empty filter panel.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._ext_group = QGroupBox("Extensions")
        self._ext_layout = QVBoxLayout(self._ext_group)
        self._ext_checks: dict[str, QCheckBox] = {}

        self._cam_group = QGroupBox("Cameras")
        self._cam_layout = QVBoxLayout(self._cam_group)
        self._cam_checks: dict[str, QCheckBox] = {}

        layout = QHBoxLayout(self)
        layout.addWidget(self._ext_group)
        layout.addWidget(self._cam_group)

    def populate(self, scan_result: ScanResult) -> None:
        """Clear and rebuild checkboxes from *scan_result*.

        Args:
            scan_result: The :class:`~app.models.scan_result.ScanResult` whose
                ``extension_counts`` and ``camera_counts`` populate the panel.
        """
        self._clear_group(self._ext_layout, self._ext_checks)
        self._clear_group(self._cam_layout, self._cam_checks)

        for ext, count in scan_result.extension_counts.items():
            self._add_check(self._ext_layout, self._ext_checks, ext, count)

        for cam, count in scan_result.camera_counts.items():
            self._add_check(self._cam_layout, self._cam_checks, cam, count)

    def selected_extensions(self) -> set[str]:
        """Return the set of checked extension strings."""
        return {ext for ext, cb in self._ext_checks.items() if cb.isChecked()}

    def selected_cameras(self) -> set[str]:
        """Return the set of checked camera strings."""
        return {cam for cam, cb in self._cam_checks.items() if cb.isChecked()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_group(
        self, layout: QVBoxLayout, checks: dict[str, QCheckBox]
    ) -> None:
        for cb in checks.values():
            layout.removeWidget(cb)
            cb.deleteLater()
        checks.clear()

    def _add_check(
        self,
        layout: QVBoxLayout,
        checks: dict[str, QCheckBox],
        key: str,
        count: int,
    ) -> None:
        cb = QCheckBox(f"{key} ({count})")
        cb.setChecked(True)
        cb.toggled.connect(lambda _checked: self.filter_changed.emit())
        layout.addWidget(cb)
        checks[key] = cb
