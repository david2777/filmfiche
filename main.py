"""Entry point — boots QApplication and shows the main window."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow

_ICON = Path(__file__).parent / "resources" / "icon.svg"


def main() -> None:
    """Create the application, show the main window, and start the event loop."""
    app = QApplication(sys.argv)
    app.setOrganizationName("filmfiche")
    app.setApplicationName("filmfiche")
    if _ICON.exists():
        app.setWindowIcon(QIcon(str(_ICON)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
