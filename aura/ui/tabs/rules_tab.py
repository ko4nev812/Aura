"""«Правила» — таблица AppRule (ТЗ §3.4, §4.1.3).

UI и CRUD готовы; применение правил (пауза/ducking/смена пака) подключается в
фазе 3 вместе с Activity Monitor.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.service import AuraService
from ...library.manager import RuleInfo
from ...db.models import RULE_MODES

MODE_LABELS = {
    "pause": "пауза (не мешать)",
    "duck": "приглушить",
    "ignore": "игнорировать",
    "custom": "свой пак",
}


class RuleDialog(QDialog):
    def __init__(self, service: AuraService, rule: RuleInfo | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.rule = rule
        self.setWindowTitle("Правило" if rule else "Новое правило")
        self.setMinimumWidth(430)

        form = QFormLayout(self)
        form.setSpacing(9)

        self.process = QLineEdit(rule.process_name if rule else "")
        self.process.setPlaceholderText("chrome.exe")
        form.addRow("Процесс", self.process)

        self.title_pattern = QLineEdit(rule.title_pattern or "" if rule else "")
        self.title_pattern.setPlaceholderText("regex по заголовку, напр. .*YouTube.*")
        form.addRow("Заголовок (regex)", self.title_pattern)

        self.mode = QComboBox()
        for value in RULE_MODES:
            self.mode.addItem(MODE_LABELS.get(value, value), value)
        if rule:
            index = self.mode.findData(rule.mode)
            if index >= 0:
                self.mode.setCurrentIndex(index)
        self.mode.currentIndexChanged.connect(self._sync)
        form.addRow("Режим", self.mode)

        self.packs = QComboBox()
        self.packs.addItem("(не выбрано)", "")
        for pack in service.library.list_packs(with_tracks=False):
            self.packs.addItem(pack.name, pack.id)
        form.addRow("Пак для custom", self.packs)

        self.duck = QDoubleSpinBox()
        self.duck.setRange(0.0, 1.0)
        self.duck.setSingleStep(0.05)
        self.duck.setValue(rule.duck_level if rule else 0.2)
        form.addRow("Громкость при ducking", self.duck)

        self.priority = QSpinBox()
        self.priority.setRange(-100, 100)
        self.priority.setValue(rule.priority if rule else 0)
        form.addRow("Приоритет", self.priority)

        self.enabled = QCheckBox("Правило включено")
        self.enabled.setChecked(rule.enabled if rule else True)
        form.addRow("", self.enabled)

        hint = QLabel(
            "Примеры: chrome.exe + .*YouTube.* → пауза; zoom.exe → приглушить; "
            "code.exe → разрешить музыку. Срабатывание — с фазы 3."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow("", hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._sync()

    def _sync(self) -> None:
        self.packs.setEnabled(self.mode.currentData() == "custom")
        self.duck.setEnabled(self.mode.currentData() == "duck")

    def _on_save(self) -> None:
        if not self.process.text().strip():
            QMessageBox.warning(self, "Проверьте поля", "Имя процесса обязательно")
            return
        self.accept()

    def values(self) -> dict[str, object]:
        packs = self.packs.currentData()
        return {
            "process_name": self.process.text().strip().lower(),
            "title_pattern": self.title_pattern.text().strip() or None,
            "mode": str(self.mode.currentData()),
            "custom_pack_ids": [str(packs)] if packs else [],
            "priority": self.priority.value(),
            "duck_level": self.duck.value(),
            "enabled": self.enabled.isChecked(),
        }


class RulesTab(QWidget):
    COLUMNS = ("Процесс", "Заголовок (regex)", "Режим", "Пак", "Duck", "Приоритет", "Вкл")

    def __init__(self, service: AuraService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Black/white списки приложений")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        self.add_button = QPushButton("Добавить правило")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(self.add_rule)
        header.addWidget(self.add_button)
        self.edit_button = QPushButton("Изменить")
        self.edit_button.clicked.connect(self.edit_rule)
        header.addWidget(self.edit_button)
        self.remove_button = QPushButton("Удалить")
        self.remove_button.setObjectName("ghost")
        self.remove_button.clicked.connect(self.remove_rule)
        header.addWidget(self.remove_button)
        root.addLayout(header)

        self.note = QLabel(
            "Схема и интерфейс готовы. Реакция плеера на правила (пауза, ducking, "
            "подмена пака) подключается в фазе 3 вместе с Activity Monitor."
        )
        self.note.setObjectName("hint")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        root.addWidget(self.table, 1)

        self.status = QLabel("—")
        self.status.setObjectName("hint")
        root.addWidget(self.status)
        self.reload()

    def reload(self) -> None:
        rules = self.service.library.list_rules()
        pack_names = {pack.id: pack.name for pack in self.service.library.list_packs(with_tracks=False)}
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            pack = ", ".join(pack_names.get(pid, pid[:8]) for pid in rule.custom_pack_ids) or "—"
            cells = (
                rule.process_name,
                rule.title_pattern or "—",
                MODE_LABELS.get(rule.mode, rule.mode),
                pack,
                f"{rule.duck_level:.2f}" if rule.mode == "duck" else "—",
                str(rule.priority),
                "да" if rule.enabled else "нет",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, rule.id)
                    item.setForeground(QColor("#cbbcff"))
                if not rule.enabled:
                    item.setForeground(QColor("#65657f"))
                self.table.setItem(row, column, item)
        self.status.setText(f"Правил: {len(rules)}")
        self._sync_buttons()

    def _selected_rule_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _sync_buttons(self) -> None:
        has_selection = self._selected_rule_id() is not None
        self.edit_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)

    def add_rule(self) -> None:
        dialog = RuleDialog(self.service, None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.service.library.add_rule(**dialog.values())  # type: ignore[arg-type]
        self.reload()

    def edit_rule(self) -> None:
        rule_id = self._selected_rule_id()
        if rule_id is None:
            return
        current = next((r for r in self.service.library.list_rules() if r.id == rule_id), None)
        if current is None:
            return
        dialog = RuleDialog(self.service, current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.service.library.update_rule(rule_id, **dialog.values())
        self.reload()

    def remove_rule(self) -> None:
        rule_id = self._selected_rule_id()
        if rule_id is None:
            return
        if QMessageBox.question(self, "Удалить правило?", "Удалить выбранное правило?") != QMessageBox.StandardButton.Yes:
            return
        self.service.library.delete_rule(rule_id)
        self.reload()
