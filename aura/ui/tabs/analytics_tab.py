"""«Аналитика» — сводка по библиотеке и фидбеку (ТЗ §4.1.4).

Графики (energy×valence карта, лайки по времени) — фаза 5; здесь счётчики и
первые агрегаты, которые уже считает схема фазы 1.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)

from ...core.service import AuraService
from ...db.database import Database
from ...db.models import Feedback, Pack, PlayEvent, Track
from ..widgets import format_long_duration
from sqlalchemy import func, select


class AnalyticsTab(QWidget):
    def __init__(self, service: AuraService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        title = QLabel("Аналитика")
        title.setObjectName("title")
        root.addWidget(title)
        hint = QLabel(
            "Данные собираются с фазы 1 (история воспроизведений) и фазы 4 (лайки). "
            "Графики и «карта вкуса» появятся в фазе 5."
        )
        hint.setObjectName("hint")
        root.addWidget(hint)

        cards = QGridLayout()
        cards.setSpacing(10)
        self.card_widgets: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(
            (
                ("packs", "паков"),
                ("tracks", "треков"),
                ("playable", "включено"),
                ("analyzed", "проанализировано"),
                ("duration", "длительность"),
                ("plays", "воспроизведений"),
                ("likes", "лаиков"),
                ("dislikes", "дизлаиков"),
            )
        ):
            box = QGroupBox(caption)
            layout = QVBoxLayout(box)
            value = QLabel("0")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setStyleSheet("font-size: 22px; font-weight: 700; color: #d8ccff; border: none;")
            layout.addWidget(value)
            self.card_widgets[key] = value
            cards.addWidget(box, index // 4, index % 4)
        root.addLayout(cards)

        self.top_table = QTableWidget(0, 4)
        self.top_table.setHorizontalHeaderLabels(("Трек", "Пак", "Помощь?", "Рейтинг"))
        self.top_table.verticalHeader().setVisible(False)
        self.top_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.top_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.top_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.top_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.top_table.setMaximumHeight(230)
        root.addWidget(self.top_table)

        self.empty_note = QLabel("Пока пусто: включите автовоспроизведение или лайкните пару треков.")
        self.empty_note.setObjectName("hint")
        root.addWidget(self.empty_note)
        root.addStretch()

    def showEvent(self, event) -> None:  # noqa: N802, ARG002 - Qt API
        self.reload()

    def reload(self) -> None:
        stats = self.service.library.stats()
        feedback = self.service.library.feedback_totals()
        plays = self._play_counts()
        self.card_widgets["packs"].setText(str(stats["packs"]))
        self.card_widgets["tracks"].setText(str(stats["tracks"]))
        self.card_widgets["playable"].setText(str(stats["playable"]))
        self.card_widgets["analyzed"].setText(str(stats["analyzed"]))
        self.card_widgets["duration"].setText(format_long_duration(stats["duration_sec"]))
        self.card_widgets["plays"].setText(str(plays["total"]))
        self.card_widgets["likes"].setText(str(feedback["likes"]))
        self.card_widgets["dislikes"].setText(str(feedback["dislikes"]))
        self._reload_top(plays["total"] or feedback["total"])

    def _play_counts(self) -> dict[str, int]:
        with self.service.db.new_session() as session:
            total = session.scalar(select(func.count(PlayEvent.id))) or 0
        return {"total": int(total)}

    def _reload_top(self, activity: int = 0) -> None:
        rows = self._top_rows()
        self.top_table.setRowCount(len(rows))
        for index, (title, pack_name, plays, score) in enumerate(rows):
            for column, text in enumerate((title, pack_name, f"{plays} проигр.", score)):
                item = QTableWidgetItem(text)
                if column == 3 and text.startswith("−"):
                    item.setForeground(QColor("#f87171"))
                self.top_table.setItem(index, column, item)
        self.empty_note.setVisible(activity == 0)
        self.empty_note.setText(
            "История пуста: включите автовоспроизведение или лайкните пару треков — "
            "здесь появится топ прослушиваний."
            if activity == 0
            else ""
        )

    def _top_rows(self) -> list[tuple[str, str, int, str]]:
        db: Database = self.service.db
        with db.new_session() as session:
            rows = session.execute(
                select(
                    Track.title,
                    Pack.name,
                    func.count(PlayEvent.id).label("plays"),
                    func.coalesce(func.sum(Feedback.rating), 0).label("score"),
                )
                .select_from(Track)
                .join(Pack, Pack.id == Track.pack_id)
                .outerjoin(PlayEvent, PlayEvent.track_id == Track.id)
                .outerjoin(Feedback, Feedback.track_id == Track.id)
                .group_by(Track.id)
                .order_by(func.count(PlayEvent.id).desc())
                .limit(12)
            ).all()
        result: list[tuple[str, str, int, str]] = []
        for title, pack_name, plays, score in rows:
            value = int(score or 0)
            label = f"+{value}" if value > 0 else (f"−{abs(value)}" if value < 0 else "0")
            result.append((str(title), str(pack_name), int(plays or 0), label))
        return result
