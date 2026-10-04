"""Neon-dark theme: QSS + programmatically drawn icons (ТЗ §4.1)."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt, QRectF
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

ACCENT_A = QColor(168, 85, 247)  # violet
ACCENT_B = QColor(56, 132, 255)  # blue
ACCENT_C = QColor(34, 211, 238)  # cyan highlight

STATE_COLORS = {
    "playing": QColor(74, 222, 128),
    "loading": QColor(129, 140, 248),
    "fading": QColor(129, 140, 248),
    "paused": QColor(250, 204, 21),
    "silence": QColor(234, 179, 8),
    "idle": QColor(148, 163, 184),
    "ducked": QColor(248, 113, 113),
    "error": QColor(248, 113, 113),
}

QSS = """
* { font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 13px; }
QWidget { background: #0d0d14; color: #e6e6f0; }
QMainWindow, QDialog { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #0b0b12, stop:0.55 #101024, stop:1 #0b0b12); }
QToolTip { background: #171728; color: #e6e6f0; border: 1px solid #3b2d6b; padding: 6px; }

QTabWidget::pane { border: 1px solid #22223a; border-radius: 10px; background: #111120; top: -1px; }
QTabBar::tab { background: transparent; color: #8b8ba7; padding: 9px 18px; margin-right: 4px;
    border: 1px solid transparent; border-bottom: none; border-top-left-radius: 9px;
    border-top-right-radius: 9px; }
QTabBar::tab:hover { color: #d6d6ea; background: #171728; }
QTabBar::tab:selected { color: #ffffff; background: qlineargradient(x1:0, y1:1, x2:1, y2:0,
    stop:0 rgba(168,85,247,0.30), stop:1 rgba(56,132,255,0.30));
    border: 1px solid #453475; }

QPushButton { background: #1a1a2e; border: 1px solid #2f2f52; border-radius: 8px;
    padding: 7px 14px; color: #dedeef; }
QPushButton:hover { border-color: #7c4dff; background: #20203a; }
QPushButton:pressed { background: #14141f; }
QPushButton:disabled { color: #5a5a72; border-color: #23233a; background: #141420; }
QPushButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 rgba(168,85,247,0.45), stop:1 rgba(56,132,255,0.45)); border-color: #9d6bff; color: white; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #8b5cf6, stop:1 #2563eb); border: none; color: white; font-weight: 600; padding: 9px 18px; }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #9d74ff, stop:1 #3b78ff); }
QPushButton#ghost { background: transparent; border: 1px solid #2f2f52; }
QPushButton#transport { border-radius: 16px; padding: 6px 12px; font-size: 15px; min-width: 34px; }
QPushButton#transportBig { border-radius: 20px; min-width: 40px; padding: 8px 14px; font-size: 17px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8b5cf6, stop:1 #2563eb);
    border: none; color: white; }
QPushButton#transportBig:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #9d74ff, stop:1 #3b78ff); }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
    background: #14141f; border: 1px solid #2b2b47; border-radius: 7px; padding: 6px 8px; color: #eceaf7;
    selection-background-color: #6d43d8; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #7c4dff; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #14141f; border: 1px solid #3b2d6b;
    selection-background-color: #2b2350; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3b3b60;
    background: #14141f; }
QCheckBox::indicator:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #a855f7, stop:1 #3884ff); border-color: #a855f7; image: none; }

QSlider::groove:horizontal { height: 5px; background: #23233c; border-radius: 3px; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #a855f7, stop:1 #3884ff); border-radius: 3px; }
QSlider::handle:horizontal { width: 13px; height: 13px; margin: -5px 0; border-radius: 6px;
    background: #f1ecff; border: 1px solid #7c4dff; }
QSlider::handle:horizontal:hover { background: white; }

QTreeWidget, QTreeView, QTableView, QListView {
    background: #101019; border: 1px solid #22223a; border-radius: 8px; padding: 4px; }
QTreeWidget::item, QTableView::item { padding: 5px 4px; border-radius: 5px; }
QTreeWidget::item:hover, QTableView::item:hover { background: #1b1b2e; }
QTreeWidget::item:selected, QTableView::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 rgba(168,85,247,0.35), stop:1 rgba(56,132,255,0.35)); color: white; }
QHeaderView::section { background: #16162a; color: #a0a0bd; border: none; padding: 6px;
    border-bottom: 1px solid #2b2b47; }

QProgressBar { background: #16162a; border: 1px solid #26264010; border-radius: 6px; height: 12px;
    text-align: center; color: #cfcfe4; font-size: 11px; }
QProgressBar::chunk { border-radius: 5px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #a855f7, stop:1 #3884ff); }

QGroupBox { border: 1px solid #24243c; border-radius: 10px; margin-top: 14px; padding: 10px;
    font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #b6a8ff; }

QLabel#title { font-size: 21px; font-weight: 700; color: white; }
QLabel#subtitle { font-size: 13px; color: #9a9ab5; }
QLabel#trackTitle { font-size: 17px; font-weight: 600; color: #f2eeff; }
QLabel#meta { color: #9a9ab5; font-size: 12px; }
QLabel#badge { background: #1d1d33; border: 1px solid #35315c; border-radius: 9px;
    padding: 3px 10px; color: #cbbcff; }
QLabel#hint { color: #6f6f8c; font-size: 12px; }

QStatusBar { background: #0f0f18; color: #8f8fae; border-top: 1px solid #22223a; }
QScrollBar:vertical { background: #101019; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #2c2c4a; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #453575; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { background: #101019; height: 11px; }
QScrollBar::handle:horizontal { background: #2c2c4a; border-radius: 5px; min-width: 24px; }
"""


def state_color(key: str) -> QColor:
    return STATE_COLORS.get(key, STATE_COLORS["idle"])


def orb_icon(size: int = 64, *, glow: str | None = None) -> QIcon:
    """App icon: violet/blue orb with an audio-wave glyph."""
    pixmap = _pixmap(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, ACCENT_A)
    gradient.setColorAt(0.6, ACCENT_B)
    gradient.setColorAt(1.0, ACCENT_C)

    margin = size * 0.08
    if glow:
        halo = QColor(glow)
        halo.setAlpha(90)
        painter.setBrush(QBrush(halo))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(margin * 0.4, margin * 0.4, size - margin * 0.8, size - margin * 0.8))

    painter.setBrush(QBrush(gradient))
    painter.setPen(QPen(QColor(255, 255, 255, 60), max(1.0, size * 0.02)))
    painter.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))

    painter.setPen(QPen(QColor(255, 255, 255, 235), max(1.5, size * 0.055), cap=Qt.PenCapStyle.RoundCap))
    bars = (0.38, 0.62, 0.28, 0.52)
    step = size * 0.13
    start_x = size / 2 - step * 1.5
    for index, height in enumerate(bars):
        x = start_x + index * step
        half = size * height / 2
        painter.drawLine(QPointF(x, size / 2 - half), QPointF(x, size / 2 + half))
    painter.end()
    return QIcon(pixmap)


def badge_icon(color: str | QColor, size: int = 22) -> QIcon:
    """Round status dot used by the tray/taskbar indicator."""
    if isinstance(color, str):
        color = state_color(color)
    pixmap = _pixmap(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color.lighter(150), max(1.0, size * 0.06)))
    painter.setBrush(QBrush(color))
    inset = size * 0.18
    painter.drawEllipse(QRectF(inset, inset, size - 2 * inset, size - 2 * inset))
    painter.end()
    return QIcon(pixmap)


def transport_icon(kind: str, size: int = 32, color: QColor | None = None) -> QIcon:
    """Play / pause / next / prev / stop / like / dislike glyphs."""
    pixmap = _pixmap(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen_color = color or QColor(236, 234, 247)
    painter.setPen(
        QPen(
            pen_color,
            max(1.6, size * 0.07),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    painter.setBrush(QBrush(pen_color))

    unit = size / 2.0
    kind = kind.lower()
    if kind == "play":
        path = QPainterPath()
        path.moveTo(unit * 0.72, unit * 0.55)
        path.lineTo(unit * 0.72, unit * 1.45)
        path.lineTo(unit * 1.45, unit)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "pause":
        painter.drawRect(QRectF(unit * 0.72, unit * 0.6, size * 0.11, size * 0.8))
        painter.drawRect(QRectF(unit * 1.17, unit * 0.6, size * 0.11, size * 0.8))
    elif kind == "stop":
        painter.drawRect(QRectF(unit * 0.7, unit * 0.7, size * 0.6, size * 0.6))
    elif kind in ("next", "skip_next"):
        path = QPainterPath()
        path.moveTo(unit * 0.62, unit * 0.6)
        path.lineTo(unit * 0.62, unit * 1.4)
        path.lineTo(unit * 1.18, unit)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRect(QRectF(unit * 1.26, unit * 0.6, size * 0.09, size * 0.8))
    elif kind in ("prev", "skip_previous"):
        path = QPainterPath()
        path.moveTo(unit * 1.38, unit * 0.6)
        path.lineTo(unit * 1.38, unit * 1.4)
        path.lineTo(unit * 0.82, unit)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRect(QRectF(unit * 0.65, unit * 0.6, size * 0.09, size * 0.8))
    elif kind in ("like", "heart"):
        painter.setBrush(QBrush(QColor(168, 85, 247) if color is None else color))
        painter.drawPath(_heart_path(size, filled=True))
    elif kind == "outline_heart":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(_heart_path(size, filled=False))
    elif kind == "dislike":
        painter.setBrush(QBrush(QColor(248, 113, 113) if color is None else color))
        painter.translate(0, size)
        painter.scale(1, -1)
        painter.drawPath(_heart_path(size, filled=True))
    elif kind == "volume":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(size * 0.25, size * 0.25, size * 0.5, size * 0.5), 60 * 16, 60 * 16)
        painter.drawArc(QRectF(size * 0.12, size * 0.12, size * 0.76, size * 0.76), 60 * 16, 60 * 16)
        painter.setBrush(QBrush(pen_color))
        painter.drawEllipse(QRectF(unit * 0.62, unit * 0.85, size * 0.16, size * 0.16))
    elif kind == "library":
        for index in range(3):
            painter.drawRect(QRectF(size * 0.22 + index * size * 0.19, size * 0.28, size * 0.12, size * 0.46))
    elif kind == "youtube":
        painter.setBrush(QBrush(QColor(220, 60, 70)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(size * 0.14, size * 0.24, size * 0.72, size * 0.52), size * 0.14, size * 0.14)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        path = QPainterPath()
        path.moveTo(unit * 0.88, unit * 0.72)
        path.lineTo(unit * 0.88, unit * 1.28)
        path.lineTo(unit * 1.32, unit)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "spinner":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6), 45 * 16, 250 * 16)
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(size * 0.25, size * 0.25, size * 0.5, size * 0.5))
    painter.end()
    return QIcon(pixmap)


def _heart_path(size: float, *, filled: bool):  # noqa: ANN202 - QPainterPath
    path = QPainterPath()
    left = size * 0.5
    top = size * 0.32
    path.moveTo(left, size * 0.74)
    path.cubicTo(size * 0.16, size * 0.48, size * 0.24, top - size * 0.10, left - size * 0.12, top)
    path.cubicTo(size * 0.45, top + size * 0.02, left, size * 0.42, left, size * 0.46)
    path.cubicTo(left, size * 0.42, size * 0.55, top + size * 0.02, left + size * 0.12, top)
    path.cubicTo(size * 0.76, top - size * 0.10, size * 0.84, size * 0.48, left, size * 0.74)
    if filled:
        path.setFillRule(Qt.FillRule.WindingFill)
    return path


def _pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def apply_theme(app) -> None:  # noqa: ANN001 - QApplication
    app.setStyleSheet(QSS)
