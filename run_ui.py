#!/usr/bin/env python3
"""Entry point for the RoboCommand RobotX 2026 host monitor (Qt UI)."""

import sys
from PyQt5.QtWidgets import QApplication
from robocommand_ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RoboCommand")
    app.setOrganizationName("Barunastra ITS")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
