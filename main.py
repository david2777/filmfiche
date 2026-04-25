"""Entry point — boots QApplication and shows the main window."""

import sys

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow


def main() -> None:
    """Create the application, show the main window, and start the event loop."""
    app = QApplication(sys.argv)
    app.setOrganizationName("filmfiche")
    app.setApplicationName("filmfiche")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
