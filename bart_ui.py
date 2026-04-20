"""
bart_ui.py — GUI entry point for Bartholomew.

Run:
    python bart_ui.py

Or double-click the desktop shortcut created by create_shortcut.py.
"""
import sys
import os
import time
from pathlib import Path

# Load .env before importing anything from bart/
from dotenv import load_dotenv
load_dotenv()

from bart.logging_utils import setup_console_logging
from bart.logging_utils import log_process_snapshot, log_timing

setup_console_logging("bart_ui")

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


def _preload():
    """
    Load heavyweight models in the main thread before Qt starts.
    ctranslate2 (faster-whisper backend) segfaults when its thread pool
    initialises inside a QThread — preloading avoids that entirely.
    """
    started = time.perf_counter()
    print("Loading Whisper model... (first run may take a moment)")
    from bart.ears import _get_whisper_model
    _get_whisper_model()
    print("Whisper model ready.")
    log_timing("ui_preload_whisper", (time.perf_counter() - started) * 1000)
    log_process_snapshot("ui_preload_complete")


def main():
    _preload()

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
