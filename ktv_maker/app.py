from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AI KTV MV 批量制作器")
    app.setOrganizationName("UVR5KTV")
    win = MainWindow()
    win.show()
    return app.exec()
