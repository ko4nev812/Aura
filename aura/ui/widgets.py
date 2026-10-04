"""UI helper widgets used by the tabs."""

from __future__ import annotations

import datetime as dt

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QFontMetrics
from PyQt6.QtWidgets import QLabel, QSizePolicy, QWidget


def format_duration(seconds: float | int | None) -> str:
    if not seconds or seconds <= 0:
        return "--:--"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_long_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0 мин"
    hours, remainder = divmod(int(seconds), 3600)
    minutes = remainder // 60
    parts = []
    if hours:
        parts.append(f"{hours} ч")
    if minutes or not hours:
        parts.append(f"{minutes} мин")
    return " ".join(parts)


def format_size(num_bytes: int | None) -> str:
    if not num_bytes:
        return ""
    value = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return ""  # pragma: no cover


def elide(text: str, width_px: int, font_point: int = 11) -> str:
    if not text or width_px <= 0:
        return text
    metrics = QFontMetrics(_font(font_point))
    return metrics.elidedText(text, Qt.TextElideMode.ElideRight, width_px)


def _font(point: int):
    font = QLabel().font()
    font.setPointSize(point)
    return font


class PulseOrb(QWidget):
    """Gradient orb with a progress ring — stand-in for cover art (phase 1)."""

    def __init__(self, size: int = 150, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._progress = 0.0
        self._active = False
        self._phase = 0.0
        self._pulse = QPropertyAnimation(self, b"phase", self)
        self._pulse.setDuration(2400)
        self._pulse.setStartValue(0.0)
        self._pulse.setEndValue(360.0)
        self._pulse.setLoopCount(-1)
        self._pulse.setEasingCurve(QEasingCurve.Type.Linear)

    def get_phase(self) -> float:
        return self._phase

    def set_phase(self, value: float) -> None:
        self._phase = value
        self.update()

    phase = pyqtProperty(float, fget=get_phase, fset=set_phase)

    def set_progress(self, fraction: float) -> None:
        self._progress = max(0.0, min(1.0, fraction))
        self.update()

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if active:
            self._pulse.start()
        else:
            self._pulse.stop()
        self.update()

    @property
    def is_pulsing(self) -> bool:
        return self._pulse.state() == QPropertyAnimation.State.Running

    def paintEvent(self, event) -> None:  # noqa: N802, ARG002 - Qt API
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QConicalGradient, QPainter, QPen, QRadialGradient

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        glow = QColor(120, 80, 240, 70 if self._active else 32)
        radius = side * (0.44 + (0.02 if self._active else 0.0) * _sin(self._phase))
        centre = rect.center()

        radial = QRadialGradient(centre, radius * 2)
        radial.setColorAt(0.0, QColor(190, 140, 255, 220))
        radial.setColorAt(0.45, QColor(96, 70, 220, 200))
        radial.setColorAt(1.0, QColor(16, 14, 34, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(centre, radius * 1.32, radius * 1.32)
        painter.setBrush(radial)
        painter.drawEllipse(centre, radius, radius)

        ring = rect.adjusted(side * 0.045, side * 0.045, -side * 0.045, -side * 0.045)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 26), max(2.0, side * 0.03)))
        painter.drawEllipse(ring)

        if self._progress > 0:
            conical = QConicalGradient(centre, 270)
            conical.setColorAt(0.0, QColor(168, 85, 247))
            conical.setColorAt(1.0, QColor(56, 189, 248))
            pen = QPen(conical, max(2.4, side * 0.035), cap=Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            span = int(self._progress * 360 * 16)
            painter.drawArc(ring, 270 * 16, -span if span else 0)
        painter.end()


class Badge(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")


def now_label() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def _sin(degrees: float) -> float:
    import math

    return math.sin(math.radians(degrees))
