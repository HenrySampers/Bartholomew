"""
bart_ui.py — GUI entry point for Bartholomew.

Run:
    python bart_ui.py

Or double-click the desktop shortcut created by create_shortcut.py.
"""
import sys
import os
from pathlib import Path

# Load .env before importing anything from bart/
from dotenv import load_dotenv
load_dotenv()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Generate icon on first run if missing
ASSETS = Path(__file__).parent / "assets"
ICON_PATH = ASSETS / "bart.ico"
if not ICON_PATH.exists():
    try:
        from bart.generate_icon import generate
        generate()
    except Exception as e:
        print(f"[icon] could not generate icon: {e}")

from bart.ui.window import BartWindow


def main():
    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Bartholomew")
    app.setOrganizationName("Bart")

    if ICON_PATH.exists():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    window = BartWindow(icon_path=ICON_PATH if ICON_PATH.exists() else None)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
