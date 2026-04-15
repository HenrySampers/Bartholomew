"""
BartWindow — main PyQt6 UI.

Layout (340 x 520, resizable, frameless):
  ┌─────────────────────────────────────┐
  │  ● BART                         [×] │  ← draggable title bar
  ├─────────────────────────────────────┤
  │          STATE BANNER               │  ← state label (coloured)
  ├─────────────────────────────────────┤
  │                                     │
  │         WAVEFORM (140px)            │
  │                                     │
  ├─────────────────────────────────────┤
  │  You: <transcript>                  │
  │  Bart: <reply>                      │
  ├─────────────────────────────────────┤
  │  CPU ██░░  RAM ██░░   🌤 weather    │  ← stats row
  ├─────────────────────────────────────┤
  │           [SPACE]  [■ STOP]         │  ← action buttons
  └─────────────────────────────────────┘
"""
import os
import time
import threading

import psutil
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow,
    QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..state import BartState, STATE_LABELS
from .waveform import WaveformWidget
from .worker import BartWorker

# Colours
_BG = "#0d0d0d"
_SURFACE = "#161616"
_TEXT = "#e0e0e0"
_DIM = "#555555"

_STATE_COLORS = {
    BartState.IDLE:       "#4ecdc4",
    BartState.LISTENING:  "#ff6b6b",
    BartState.THINKING:   "#ffd93d",
    BartState.SPEAKING:   "#6bcb77",
    BartState.CONFIRMING: "#ff922b",
}

_STATE_HINTS = {
    BartState.IDLE:       "hold SPACE or use wake word",
    BartState.LISTENING:  "listening...",
    BartState.THINKING:   "thinking...",
    BartState.SPEAKING:   "speaking",
    BartState.CONFIRMING: "waiting for confirmation",
}


class BartWindow(QMainWindow):
    def __init__(self, icon_path=None):
        super().__init__()
        self._drag_pos = QPoint()
        self._current_state = BartState.IDLE
        self._weather_text = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(340, 520)

        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self._apply_theme()

        # Worker
        self._worker = BartWorker()
        self._worker.state_changed.connect(self._on_state_changed)
        self._worker.transcript_ready.connect(self._on_transcript)
        self._worker.reply_ready.connect(self._on_reply)
        self._worker.shutdown_complete.connect(self._on_shutdown)
        self._worker.start()

        # Stats refresh (every 3 s)
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start(3000)
        self._refresh_stats()

        # Weather (fetch once, async)
        self._weather_text = "..."
        threading.Thread(target=self._fetch_weather, daemon=True).start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        layout.addWidget(self._make_title_bar())

        # State banner
        self._state_label = QLabel("idle — hold SPACE to speak")
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_label.setFixedHeight(32)
        self._state_label.setObjectName("state_banner")
        layout.addWidget(self._state_label)

        # Waveform
        self._waveform = WaveformWidget()
        self._waveform.setFixedHeight(140)
        layout.addWidget(self._waveform)

        # Transcript area
        transcript_widget = QWidget()
        transcript_widget.setObjectName("transcript_area")
        t_layout = QVBoxLayout(transcript_widget)
        t_layout.setContentsMargins(14, 10, 14, 10)
        t_layout.setSpacing(6)

        self._you_label = QLabel("You: —")
        self._you_label.setWordWrap(True)
        self._you_label.setObjectName("you_label")

        self._bart_label = QLabel("Bart: —")
        self._bart_label.setWordWrap(True)
        self._bart_label.setObjectName("bart_label")

        t_layout.addWidget(self._you_label)
        t_layout.addWidget(self._bart_label)
        layout.addWidget(transcript_widget)

        # Separator
        layout.addWidget(self._make_separator())

        # Stats row
        stats_widget = QWidget()
        stats_widget.setObjectName("stats_row")
        s_layout = QHBoxLayout(stats_widget)
        s_layout.setContentsMargins(14, 6, 14, 6)
        s_layout.setSpacing(10)

        self._cpu_bar = self._make_mini_bar("CPU", s_layout)
        self._ram_bar = self._make_mini_bar("RAM", s_layout)
        self._weather_label = QLabel("...")
        self._weather_label.setObjectName("weather_label")
        s_layout.addStretch()
        s_layout.addWidget(self._weather_label)
        layout.addWidget(stats_widget)

        # Action buttons
        layout.addWidget(self._make_separator())
        layout.addWidget(self._make_buttons())

    def _make_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("title_bar")
        bar.setFixedHeight(38)
        bar.setCursor(Qt.CursorShape.SizeAllCursor)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 10, 0)

        dot = QLabel("●")
        dot.setObjectName("dot")
        dot.setFixedWidth(14)
        lay.addWidget(dot)

        title = QLabel("BART")
        title.setObjectName("title_text")
        lay.addWidget(title)
        lay.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("close_btn")
        close_btn.setFixedSize(22, 22)
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.clicked.connect(self._quit)
        lay.addWidget(close_btn)

        bar.mousePressEvent = self._title_mouse_press
        bar.mouseMoveEvent = self._title_mouse_move
        return bar

    def _make_buttons(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("button_row")
        lay = QHBoxLayout(widget)
        lay.setContentsMargins(14, 8, 14, 12)
        lay.setSpacing(10)

        space_btn = QPushButton("SPACE  ·  speak")
        space_btn.setObjectName("space_btn")
        space_btn.clicked.connect(self._on_space_clicked)
        space_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        space_btn.setFixedHeight(34)
        space_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        stop_btn = QPushButton("■  STOP")
        stop_btn.setObjectName("stop_btn")
        stop_btn.clicked.connect(self._on_stop_clicked)
        stop_btn.setFixedHeight(34)
        stop_btn.setFixedWidth(90)
        stop_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay.addWidget(space_btn)
        lay.addWidget(stop_btn)
        return widget

    def _make_separator(self) -> QWidget:
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setObjectName("separator")
        return sep

    def _make_mini_bar(self, label: str, layout: QHBoxLayout):
        lbl = QLabel(label)
        lbl.setObjectName("stats_label")
        layout.addWidget(lbl)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setFixedWidth(52)
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        bar.setObjectName("mini_bar")
        layout.addWidget(bar)
        return bar

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget#root {{
                background: {_BG};
                border: 1px solid #2a2a2a;
                border-radius: 8px;
            }}
            QWidget#title_bar {{
                background: {_SURFACE};
                border-radius: 8px 8px 0 0;
            }}
            QLabel#dot {{
                color: #4ecdc4;
                font-size: 11px;
            }}
            QLabel#title_text {{
                color: {_TEXT};
                font-family: Consolas, monospace;
                font-size: 12px;
                font-weight: bold;
                letter-spacing: 3px;
            }}
            QPushButton#close_btn {{
                background: transparent;
                color: {_DIM};
                border: none;
                font-size: 18px;
            }}
            QPushButton#close_btn:hover {{
                color: #ff6b6b;
            }}
            QLabel#state_banner {{
                background: {_SURFACE};
                color: #4ecdc4;
                font-family: Consolas, monospace;
                font-size: 11px;
                letter-spacing: 1px;
                border-bottom: 1px solid #2a2a2a;
            }}
            QWidget#transcript_area {{
                background: {_BG};
            }}
            QLabel#you_label {{
                color: #aaaaaa;
                font-family: Consolas, monospace;
                font-size: 11px;
            }}
            QLabel#bart_label {{
                color: {_TEXT};
                font-family: Consolas, monospace;
                font-size: 11px;
            }}
            QWidget#separator {{
                background: #2a2a2a;
            }}
            QWidget#stats_row {{
                background: {_SURFACE};
            }}
            QLabel#stats_label {{
                color: {_DIM};
                font-family: Consolas, monospace;
                font-size: 10px;
            }}
            QLabel#weather_label {{
                color: {_DIM};
                font-family: Consolas, monospace;
                font-size: 10px;
            }}
            QProgressBar#mini_bar {{
                background: #2a2a2a;
                border: none;
                border-radius: 3px;
            }}
            QProgressBar#mini_bar::chunk {{
                background: #4ecdc4;
                border-radius: 3px;
            }}
            QWidget#button_row {{
                background: {_SURFACE};
                border-radius: 0 0 8px 8px;
            }}
            QPushButton#space_btn {{
                background: #1e1e1e;
                color: #4ecdc4;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 11px;
                letter-spacing: 1px;
            }}
            QPushButton#space_btn:hover {{
                background: #252525;
                border-color: #4ecdc4;
            }}
            QPushButton#space_btn:pressed {{
                background: #4ecdc4;
                color: #0d0d0d;
            }}
            QPushButton#stop_btn {{
                background: #1e1e1e;
                color: #ff6b6b;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 11px;
                letter-spacing: 1px;
            }}
            QPushButton#stop_btn:hover {{
                background: #252525;
                border-color: #ff6b6b;
            }}
            QPushButton#stop_btn:pressed {{
                background: #ff6b6b;
                color: #0d0d0d;
            }}
        """)

    # ------------------------------------------------------------------
    # Key events — absorb SPACE so it never activates a focused button
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            event.accept()  # swallow — the keyboard library handles SPACE globally
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Draggable title bar
    # ------------------------------------------------------------------

    def _title_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_space_clicked(self):
        """Simulate a SPACE press so the worker triggers listen."""
        import keyboard
        keyboard.press_and_release("space")

    def _on_stop_clicked(self):
        """Interrupt Bart mid-sentence. Exchange is NOT saved to memory."""
        self._worker.interrupt()

    # ------------------------------------------------------------------
    # Worker signals
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def _on_state_changed(self, state: BartState):
        self._current_state = state
        self._waveform.set_state(state)

        color = _STATE_COLORS.get(state, "#ffffff")
        hint = _STATE_HINTS.get(state, "")
        self._state_label.setText(hint)
        self._state_label.setStyleSheet(
            f"color: {color}; background: {_SURFACE}; "
            f"font-family: Consolas, monospace; font-size: 11px; "
            f"letter-spacing: 1px; border-bottom: 1px solid #2a2a2a;"
        )
        # Update dot colour in title bar
        dot = self.findChild(QLabel, "dot")
        if dot:
            dot.setStyleSheet(f"color: {color}; font-size: 11px;")

    @pyqtSlot(str)
    def _on_transcript(self, text: str):
        # Truncate for display
        display = text if len(text) <= 80 else text[:77] + "..."
        self._you_label.setText(f"You: {display}")
        self._bart_label.setText("Bart: ...")

    @pyqtSlot(str)
    def _on_reply(self, text: str):
        display = text if len(text) <= 120 else text[:117] + "..."
        self._bart_label.setText(f"Bart: {display}")

    @pyqtSlot()
    def _on_shutdown(self):
        QApplication.quit()

    # ------------------------------------------------------------------
    # Stats / weather
    # ------------------------------------------------------------------

    def _refresh_stats(self):
        cpu = int(psutil.cpu_percent(interval=None))
        ram = int(psutil.virtual_memory().percent)
        self._cpu_bar.setValue(cpu)
        self._ram_bar.setValue(ram)
        self._weather_label.setText(self._weather_text)

    def _fetch_weather(self):
        try:
            import requests
            loc = os.getenv("WEATHER_LOCATION", "").strip().replace(" ", "+")
            url = f"https://wttr.in/{loc}?format=3" if loc else "https://wttr.in/?format=3"
            r = requests.get(url, timeout=6)
            self._weather_text = r.text.strip()[:30]
        except Exception:
            self._weather_text = ""

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def _quit(self):
        self._worker.request_shutdown()
        self._worker.wait(3000)
        QApplication.quit()

    def closeEvent(self, event):
        self._quit()
        event.accept()
