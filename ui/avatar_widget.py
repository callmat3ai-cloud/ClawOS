"""
ClawOS Avatar Widget — animated AI face that reacts to conversation.
States: idle, listening, thinking, speaking, happy, surprised, error.

The avatar uses PyQt6 drawing + animation to create a living AI companion.
Can be toggled on/off in the UI. Designed for viral demo videos.
"""
from __future__ import annotations

import math
import threading
import time
from enum import Enum

from PyQt6.QtCore import QObject, QTimer, QRectF, pyqtSignal, Qt
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QPen, QBrush,
    QLinearGradient, QRadialGradient, QFont, QTransform,
)
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QPushButton


class AvatarState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HAPPY = "happy"
    SAD = "sad"
    SURPRISED = "surprised"
    ERROR = "error"


# ── Color Palette ──────────────────────────────────────────────────────

class AvatarColors:
    """ClawOS avatar color scheme — dark futuristic."""

    SKIN = "#1a1a2e"           # Deep dark purple-blue face
    SKIN_LIGHT = "#252545"     # Lighter shade
    GLOW = "#8b5cf6"           # Purple glow
    GLOW_BRIGHT = "#a78bfa"    # Bright purple
    ACCENT = "#22d3ee"         # Cyan accent
    EYE = "#22d3ee"            # Cyan eyes
    EYE_BRIGHT = "#67e8f9"     # Bright cyan
    MOUTH = "#f472b6"          # Pink mouth
    MOUTH_LIGHT = "#fb7185"    # Light pink
    PUPIL = "#0ea5e9"          # Blue pupil
    BROW = "#6366f1"           # Purple brows
    CHEEK = "#7c3aed"          # Purple blush cheeks
    RING = "#6366f1"           # Ring color
    RING_BRIGHT = "#818cf8"    # Bright ring


# ── Avatar Widget ───────────────────────────────────────────────────────

class AvatarWidget(QWidget):
    """
    Animated AI avatar — a glowing orb face that reacts to voice/AI activity.

    States:
    - idle: Gentle pulsing glow, eyes open, neutral expression
    - listening: Eyes widen, ring spins, subtle tilt toward user
    - thinking: Eyes narrow/thinking expression, pulsing dots animation
    - speaking: Mouth animates (lip-sync), expression varies
    - happy: Wide smile, curved eyes, bright glow
    - sad: Downturned mouth, dimmed glow
    - surprised: Wide eyes, open mouth, bright flash
    - error: Red tinge, X eyes, shake animation

    Usage:
        avatar = AvatarWidget(parent)
        avatar.set_state(AvatarState.SPEAKING)
        avatar.start_lipsync()    # Start mouth animation
        avatar.stop_lipsync()     # Stop mouth animation
    """

    # Emitted when user clicks the avatar
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AvatarState.IDLE
        self._ticker = 0.0
        self._lip_open = 0.0      # 0.0 = closed, 1.0 = full open
        self._lip_target = 0.0
        self._speaking = False
        self._lipsync_thread: threading.Thread | None = None
        self._running = True
        self._brow_raise = 0.0   # 0.0 = normal, 1.0 = raised
        self._eye_wide = 0.0     # 0.0 = normal, 1.0 = wide
        self._smile = 0.0         # 0.0 = neutral, 1.0 = big smile
        self._shake = 0.0         # shake intensity
        self._pulse = 0.0         # glow pulse
        self._set_point_size()

        # Timer for smooth animation
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)  # ~60fps

        self.setMinimumSize(120, 120)
        self.setMaximumSize(200, 200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("🟣 ClawOS — Click to interact")

    def _set_point_size(self):
        """Calculate point size based on widget size."""
        s = min(self.width(), self.height())
        self._point_size = max(8, s // 10)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_point_size()

    # ── Public API ──────────────────────────────────────────────────────

    def set_state(self, state: AvatarState):
        """Change avatar state — triggers expression transition."""
        if self._state == state:
            return
        self._state = state
        # Snap expressions for state
        if state == AvatarState.LISTENING:
            self._eye_wide = 0.8
            self._brow_raise = 0.5
            self._smile = 0.1
        elif state == AvatarState.THINKING:
            self._eye_wide = 0.2
            self._brow_raise = 0.6
            self._smile = 0.0
        elif state == AvatarState.HAPPY:
            self._eye_wide = 0.5
            self._brow_raise = 0.3
            self._smile = 1.0
        elif state == AvatarState.SURPRISED:
            self._eye_wide = 1.0
            self._brow_raise = 1.0
            self._smile = 0.3
        elif state == AvatarState.SAD:
            self._eye_wide = 0.1
            self._brow_raise = -0.3
            self._smile = -0.3
        elif state == AvatarState.ERROR:
            self._shake = 1.0
            self._eye_wide = 0.3
            self._smile = -0.5
        else:  # IDLE
            self._eye_wide = 0.1
            self._brow_raise = 0.0
            self._smile = 0.0
            self._shake = 0.0
        self.update()

    def get_state(self) -> AvatarState:
        return self._state

    def start_lipsync(self):
        """Start animated mouth movement (call when TTS starts)."""
        if self._lipsync_thread and self._lipsync_thread.is_alive():
            return
        self._speaking = True
        self._running = True
        self._lipsync_thread = threading.Thread(target=self._lipsync_loop, daemon=True)
        self._lipsync_thread.start()

    def stop_lipsync(self):
        """Stop animated mouth movement (call when TTS ends)."""
        self._speaking = False
        self._lip_target = 0.0

    def mousePressEvent(self, event):
        self.clicked.emit()
        # Bounce animation on click
        self._bounce = 1.0
        super().mousePressEvent(event)

    # ── Animation ───────────────────────────────────────────────────────

    def _tick(self):
        """Called at 60fps — update all animation values."""
        self._ticker += 0.05
        self._pulse = (math.sin(self._ticker * 1.5) + 1.0) / 2.0  # 0..1

        # Smooth lip movement toward target
        self._lip_open += (self._lip_target - self._lip_open) * 0.15

        # Eye wide decay back to normal
        self._eye_wide += (0.1 - self._eye_wide) * 0.05

        # Brow raise decay
        self._brow_raise += (0.0 - self._brow_raise) * 0.03

        # Shake decay
        self._shake *= 0.9
        if self._shake < 0.01:
            self._shake = 0.0

        self.update()

    def _lipsync_loop(self):
        """Background thread — drives lip animation with natural variation."""
        import random
        while self._running:
            if self._speaking:
                # Random target mouth openness — simulates speech rhythm
                self._lip_target = random.uniform(0.2, 0.9)
                time.sleep(random.uniform(0.08, 0.25))
            else:
                self._lip_target = 0.0
                time.sleep(0.05)

    # ── Drawing ─────────────────────────────────────────────────────────

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 * 0.88

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Apply shake offset
        if self._shake > 0:
            sx = math.sin(self._ticker * 30) * self._shake * 4
            sy = math.cos(self._ticker * 25) * self._shake * 3
            painter.translate(sx, sy)

        # Determine colors based on state
        glow = QColor(AvatarColors.GLOW)
        skin = QColor(AvatarColors.SKIN)
        eye_color = QColor(AvatarColors.EYE)
        mouth_color = QColor(AvatarColors.MOUTH)

        if self._state == AvatarState.ERROR:
            glow = QColor("#ef4444")
            skin = QColor("#1a0a0a")
            eye_color = QColor("#f87171")
        elif self._state == AvatarState.HAPPY:
            glow = QColor("#22c55e")
        elif self._state == AvatarState.SURPRISED:
            glow = QColor("#fbbf24")

        # Glow intensity
        glow_alpha = int(60 + 80 * self._pulse)
        glow.setAlpha(glow_alpha)

        # ── Outer glow ring ──────────────────────────────────────────
        outer_glow = QRadialGradient(cx, cy, r * 1.1, cx, cy, r * 1.1)
        outer_glow.setColorAt(0.0, glow)
        outer_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(outer_glow))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx, cy, r * 2.2, r * 2.2)

        # ── Face circle ──────────────────────────────────────────────
        face_grad = QRadialGradient(cx - r * 0.3, cy - r * 0.3, r * 1.4, cx, cy, r)
        face_grad.setColorAt(0.0, QColor(AvatarColors.SKIN_LIGHT))
        face_grad.setColorAt(1.0, skin)
        painter.setBrush(QBrush(face_grad))
        painter.setPen(QPen(QColor(AvatarColors.RING), 2.5))
        painter.drawEllipse(cx, cy, r * 2, r * 2)

        # ── Inner ring ───────────────────────────────────────────────
        ring_r = r * 0.88
        rp = QPen(QColor(AvatarColors.RING), 1.5)
        rp.setDashPattern([4, 4])
        rp.setDashOffset(self._ticker * 5 if self._state in (
            AvatarState.LISTENING, AvatarState.SPEAKING) else 0)
        painter.setPen(rp)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(cx, cy, ring_r * 2, ring_r * 2)

        # ── Eyes ─────────────────────────────────────────────────────
        eye_y = cy - r * 0.12
        eye_spacing = r * 0.38
        eye_w = r * 0.18 * (1 + self._eye_wide * 0.4)
        eye_h = r * 0.14 * (1 + self._eye_wide * 0.5)

        # Left eye
        self._draw_eye(painter, cx - eye_spacing, eye_y, eye_w, eye_h,
                       eye_color, self._state)

        # Right eye
        self._draw_eye(painter, cx + eye_spacing, eye_y, eye_w, eye_h,
                       eye_color, self._state)

        # ── Eyebrows ─────────────────────────────────────────────────
        brow_y = eye_y - eye_h * 1.1 - r * 0.05 * self._brow_raise
        brow_tilt = self._brow_raise * 0.15

        self._draw_brow(painter, cx - eye_spacing, brow_y, r * 0.22, brow_tilt)
        self._draw_brow(painter, cx + eye_spacing, brow_y, r * 0.22, -brow_tilt)

        # ── Mouth ────────────────────────────────────────────────────
        mouth_y = cy + r * 0.28
        mouth_w = r * 0.35
        self._draw_mouth(painter, cx, mouth_y, mouth_w, self._lip_open,
                         self._smile, mouth_color, self._state)

        # ── Cheeks ───────────────────────────────────────────────────
        if self._state in (AvatarState.HAPPY, AvatarState.SPEAKING):
            cheek_alpha = int(40 * self._pulse)
            cheek_color = QColor(AvatarColors.CHEEK)
            cheek_color.setAlpha(cheek_alpha)
            painter.setBrush(QBrush(cheek_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(cx - eye_spacing * 1.3, cy + r * 0.05,
                                r * 0.18, r * 0.12)
            painter.drawEllipse(cx + eye_spacing * 1.3, cy + r * 0.05,
                                r * 0.18, r * 0.12)

        # ── Thinking dots ─────────────────────────────────────────────
        if self._state == AvatarState.THINKING:
            dot_y = cy + r * 0.1
            dot_spacing = r * 0.12
            dot_size = r * 0.06
            dot_phase = self._ticker * 2
            for i in range(3):
                offset = math.sin(dot_phase + i * 1.2) * r * 0.08
                alpha = int(100 + 100 * math.sin(dot_phase + i * 1.2))
                color = QColor(AvatarColors.EYE_BRIGHT)
                color.setAlpha(max(0, alpha))
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.PenStyle.NoPen)
                cx_dot = cx + (i - 1) * dot_spacing
                painter.drawEllipse(cx_dot, dot_y + offset, dot_size, dot_size)

        # ── State label ───────────────────────────────────────────────
        if False:  # Disabled for cleaner look
            state_label = {
                AvatarState.IDLE: "●",
                AvatarState.LISTENING: "◉",
                AvatarState.SPEAKING: "◎",
                AvatarState.THINKING: "◐",
                AvatarState.HAPPY: "☺",
                AvatarState.ERROR: "✗",
            }.get(self._state, "●")
            painter.setPen(QColor(AvatarColors.TEXT_MUTED))
            painter.setFont(QFont("Arial", 7))
            painter.drawText(w - 16, 12, state_label)

    def _draw_eye(self, painter, cx, cy, ew, eh, color, state: AvatarState):
        """Draw a single eye with appropriate shape."""
        painter.setPen(Qt.PenStyle.NoPen)

        if state == AvatarState.ERROR:
            # X eyes
            painter.setPen(QPen(color, 2.5))
            painter.drawLine(cx - ew, cy - eh, cx + ew, cy + eh)
            painter.drawLine(cx - ew, cy + eh, cx + ew, cy - eh)
            return

        # Eye white (sclera)
        white = QColor("#0f0f1a")
        painter.setBrush(QBrush(white))
        painter.drawEllipse(cx, cy, ew * 2, eh * 2)

        # Iris
        iris_r = min(ew, eh) * 0.75
        iris_grad = QRadialGradient(cx, cy, iris_r, cx, cy, iris_r)
        iris_grad.setColorAt(0.0, QColor(AvatarColors.EYE_BRIGHT))
        iris_grad.setColorAt(0.6, color)
        iris_grad.setColorAt(1.0, QColor(AvatarColors.PUPIL))
        painter.setBrush(QBrush(iris_grad))
        painter.drawEllipse(cx, cy, iris_r * 2, iris_r * 2)

        # Pupil
        pupil_r = iris_r * 0.45
        painter.setBrush(QBrush(QColor(0, 0, 0)))
        painter.drawEllipse(cx, cy, pupil_r * 2, pupil_r * 2)

        # Highlight
        hl_r = iris_r * 0.25
        hl_color = QColor(255, 255, 255, 180)
        painter.setBrush(QBrush(hl_color))
        painter.drawEllipse(cx - pupil_r * 0.3, cy - pupil_r * 0.5, hl_r, hl_r)

        # Thinking: spiral overlay
        if state == AvatarState.THINKING:
            spiral = QPainterPath()
            spiral.moveTo(cx, cy)
            for i in range(20):
                angle = i * 0.5
                rr = iris_r * 0.3 * (i / 20)
                x = cx + math.cos(angle) * rr
                y = cy + math.sin(angle) * rr
                if i == 0:
                    spiral.moveTo(x, y)
                else:
                    spiral.lineTo(x, y)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(spiral)

    def _draw_brow(self, painter, cx, cy, length, tilt: float):
        """Draw an eyebrow with natural curve."""
        painter.setPen(QPen(QColor(AvatarColors.BROW), 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Slight arc with tilt
        path = QPainterPath()
        path.moveTo(cx - length, cy + tilt * length)
        path.quadTo(cx, cy - abs(tilt) * length * 0.3,
                    cx + length, cy - tilt * length)
        painter.drawPath(path)

    def _draw_mouth(self, painter, cx, cy, mw, open_amount: float,
                     smile: float, color: QColor, state: AvatarState):
        """Draw mouth — shape varies by smile and lip sync."""
        painter.setPen(Qt.PenStyle.NoPen)

        # Vertical open amount
        mh = mw * 0.25 * open_amount

        # Smile curve offset
        smile_y = smile * mw * 0.3

        if open_amount < 0.05 and smile > 0:
            # Closed smile — curved line
            path = QPainterPath()
            path.moveTo(cx - mw, cy + smile_y)
            path.quadTo(cx, cy + smile_y - abs(smile) * mw * 0.25,
                        cx + mw, cy + smile_y)
            painter.setPen(QPen(color, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            return

        # Open mouth
        inner = QColor(80, 10, 40)  # Dark inside mouth
        inner_grad = QLinearGradient(cx - mw, cy, cx + mw, cy)
        inner_grad.setColorAt(0.0, QColor(60, 5, 30))
        inner_grad.setColorAt(0.5, QColor(80, 10, 40))
        inner_grad.setColorAt(1.0, QColor(60, 5, 30))
        painter.setBrush(QBrush(inner_grad))

        # Lip outline
        lip_path = QPainterPath()
        lip_path.moveTo(cx - mw, cy + smile_y)
        # Top lip curve
        lip_path.quadTo(cx - mw * 0.5, cy - mh * 0.3 + smile_y,
                        cx, cy - mh * 0.5 + smile_y)
        lip_path.quadTo(cx + mw * 0.5, cy - mh * 0.3 + smile_y,
                        cx + mw, cy + smile_y)
        # Bottom lip curve
        lip_path.quadTo(cx + mw * 0.5, cy + mh * 0.8 + smile_y,
                        cx, cy + mh + smile_y)
        lip_path.quadTo(cx - mw * 0.5, cy + mh * 0.8 + smile_y,
                        cx - mw, cy + smile_y)
        lip_path.closeSubpath()

        painter.drawPath(lip_path)

        # Lip color overlay
        lip_color = QColor(color)
        lip_color.setAlpha(220)
        painter.setBrush(QBrush(lip_color))
        painter.setPen(Qt.PenStyle.NoPen)
        # Inner mouth shape
        inner_w = mw * 0.85
        inner_h = max(2, mh * 0.7)
        inner_sy = smile_y + mh * 0.1
        painter.drawEllipse(cx, cy + inner_sy, inner_w, inner_h)

    # ── Cleanup ────────────────────────────────────────────────────────

    def close(self):
        self._running = False
        super().close()


# ── Avatar Toggle Button ────────────────────────────────────────────────

class AvatarToggleWidget(QWidget):
    """
    Avatar + status label + toggle button for embedding in the UI.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.avatar = AvatarWidget(self)
        self.avatar.setFixedSize(140, 140)
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignHCenter)

        self._label = QLabel("ClawOS", self)
        self._label.setStyleSheet("color: #8b5cf6; font-size: 11px; font-weight: 700;")
        self._label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._label)

        self.avatar.clicked.connect(self._on_click)

    def _on_click(self):
        self.avatar.set_state(AvatarState.HAPPY)
        QTimer.singleShot(800, lambda: self.avatar.set_state(AvatarState.IDLE))
