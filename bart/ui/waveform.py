"""
Animated waveform widget for Bart's UI.

State animations:
  IDLE       — slow breathing sine wave, teal
  LISTENING  — pulsing vertical bars reacting to a simulated mic level, red
  THINKING   — three dots bouncing in sequence, yellow
  SPEAKING   — multi-layer fast sine waves, green
  CONFIRMING — pulsing ring / concentric circles, orange
"""
import math

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush
from PyQt6.QtWidgets import QWidget

from ..state import BartState

# State accent colours (match window.py)
_COLORS = {
    BartState.IDLE:       "#4ecdc4",
    BartState.LISTENING:  "#ff6b6b",
    BartState.THINKING:   "#ffd93d",
    BartState.SPEAKING:   "#6bcb77",
    BartState.CONFIRMING: "#ff922b",
}

_BG = "#0d0d0d"
_FPS = 60


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = BartState.IDLE
        self._tick = 0          # frame counter
        self._level = 0.0       # simulated mic level (0-1) for LISTENING bars
        self.setMinimumHeight(120)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(1000 // _FPS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, state: BartState) -> None:
        self._state = state
        self._tick = 0

    def set_level(self, level: float) -> None:
        """Feed a mic RMS level (0-1) for the LISTENING animation."""
        self._level = min(1.0, max(0.0, level))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _advance(self):
        self._tick += 1
        # Decay mic level gradually so bars don't snap to zero
        self._level *= 0.85
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        painter.fillRect(self.rect(), QColor(_BG))

        state = self._state
        color = QColor(_COLORS.get(state, "#ffffff"))
        t = self._tick / _FPS  # time in seconds

        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2

        if state == BartState.IDLE:
            self._draw_breathing(painter, color, t, w, h, cx, cy)
        elif state == BartState.LISTENING:
            self._draw_bars(painter, color, t, w, h)
        elif state == BartState.THINKING:
            self._draw_dots(painter, color, t, cx, cy)
        elif state == BartState.SPEAKING:
            self._draw_waves(painter, color, t, w, h, cx, cy)
        elif state == BartState.CONFIRMING:
            self._draw_rings(painter, color, t, cx, cy)

        painter.end()

    # -- IDLE: gentle sine breath --
    def _draw_breathing(self, p, color, t, w, h, cx, cy):
        amp = h * 0.18 * (0.7 + 0.3 * math.sin(t * 1.2))
        pen = QPen(color, 2.5)
        p.setPen(pen)
        points = []
        steps = w
        for i in range(steps):
            x = i
            y = cy + amp * math.sin(2 * math.pi * (i / w) * 2 - t * 1.2)
            points.append((x, y))
        for i in range(len(points) - 1):
            p.drawLine(int(points[i][0]), int(points[i][1]),
                       int(points[i + 1][0]), int(points[i + 1][1]))

    # -- LISTENING: 12 bars, heights driven by simulated mic level + noise --
    def _draw_bars(self, p, color, t, w, h):
        bar_count = 12
        bar_w = max(4, w // (bar_count * 2))
        gap = (w - bar_count * bar_w) // (bar_count + 1)
        p.setPen(Qt_no_pen())

        for i in range(bar_count):
            # Each bar has its own noise phase
            noise = 0.5 + 0.5 * math.sin(t * (4 + i * 0.7) + i * 1.3)
            level = max(0.08, self._level * noise + 0.08 * noise)
            bar_h = max(6, int(h * 0.80 * level))
            x = gap + i * (bar_w + gap)
            y = int(cy_from_h(h) - bar_h / 2)
            alpha = int(180 + 75 * noise)
            c = QColor(color.red(), color.green(), color.blue(), alpha)
            p.setBrush(QBrush(c))
            p.drawRoundedRect(x, y, bar_w, bar_h, 3, 3)

    # -- THINKING: three bouncing dots --
    def _draw_dots(self, p, color, t, cx, cy):
        dot_r = 7
        spacing = 28
        p.setPen(Qt_no_pen())
        for i in range(3):
            phase = t * 4 - i * 0.45
            bounce = -cy * 0.25 * abs(math.sin(phase))
            x = cx + (i - 1) * spacing
            y = cy + bounce
            alpha = int(180 + 75 * abs(math.sin(phase)))
            c = QColor(color.red(), color.green(), color.blue(), alpha)
            p.setBrush(QBrush(c))
            p.drawEllipse(int(x - dot_r), int(y - dot_r), dot_r * 2, dot_r * 2)

    # -- SPEAKING: two overlapping sine waves --
    def _draw_waves(self, p, color, t, w, h, cx, cy):
        layers = [
            (h * 0.30, 3.0, t * 3.5, 2.5),
            (h * 0.18, 5.0, t * 5.0 + 1.0, 1.5),
        ]
        for amp, freq, phase, width in layers:
            pen = QPen(QColor(color.red(), color.green(), color.blue(), 200), width)
            p.setPen(pen)
            prev_x, prev_y = None, None
            for i in range(w):
                x = i
                y = cy + amp * math.sin(2 * math.pi * freq * (i / w) - phase)
                if prev_x is not None:
                    p.drawLine(int(prev_x), int(prev_y), int(x), int(y))
                prev_x, prev_y = x, y

    # -- CONFIRMING: pulsing concentric rings --
    def _draw_rings(self, p, color, t, cx, cy):
        p.setPen(Qt_no_pen())
        ring_count = 3
        for i in range(ring_count):
            phase = t * 2.5 - i * 0.7
            r = 20 + 22 * i + 10 * abs(math.sin(phase))
            alpha = int(200 * (1 - i / ring_count) * abs(math.sin(phase + 0.5)))
            alpha = max(30, alpha)
            c = QColor(color.red(), color.green(), color.blue(), alpha)
            p.setBrush(QBrush(c))
            p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cy_from_h(h):
    return h / 2


def Qt_no_pen():
    pen = QPen()
    pen.setStyle(0)  # Qt.PenStyle.NoPen
    return pen
