"""«Настройки» — плеер, scheduler, приватность, пути (ТЗ §4.1.5)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import save_settings
from ...core.service import AuraService
from ...scheduler.base import SchedulerFactory

BACKEND_HINTS = {
    "random": "случайный выбор с penalty на повторы (фаза 1)",
    "thompson": "Thompson Sampling — фаза 4",
    "epsilon_greedy": "ε-greedy bandit — фаза 4",
    "lightgbm": "Learning-to-Rank — фаза 5",
    "dqn": "Reinforcement Learning — фаза 6",
}


class SettingsTab(QWidget):
    def __init__(self, service: AuraService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.settings = service.settings
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroller)

        body = QWidget()
        scroller.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(14)

        layout.addWidget(self._build_playback())
        layout.addWidget(self._build_scheduler())
        layout.addWidget(self._build_privacy())
        layout.addWidget(self._build_paths())
        layout.addStretch()
        layout.addWidget(self._build_footer())

    # ----------------------------------------------------------------- groups

    def _build_playback(self) -> QGroupBox:
        box = QGroupBox("Воспроизведение")
        form = QFormLayout(box)
        form.setSpacing(9)

        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        self.volume.setValue(self.settings.volume)
        self.volume.valueChanged.connect(self._mark_dirty)
        form.addRow("Громкость по умолчанию", self.volume)

        self.shuffle = QCheckBox("Перемешивать (иначе — по алфавиту внутри паков)")
        self.shuffle.setChecked(self.settings.shuffle)
        self.shuffle.toggled.connect(self._mark_dirty)
        form.addRow("", self.shuffle)

        self.crossfade = QCheckBox("Кроссфейд между треками")
        self.crossfade.setChecked(self.settings.crossfade_enabled)
        self.crossfade.toggled.connect(self._mark_dirty)
        form.addRow("", self.crossfade)

        self.crossfade_sec = QDoubleSpinBox()
        self.crossfade_sec.setRange(0.5, 8.0)
        self.crossfade_sec.setSingleStep(0.5)
        self.crossfade_sec.setSuffix(" c")
        self.crossfade_sec.setValue(self.settings.crossfade_sec)
        self.crossfade_sec.valueChanged.connect(self._mark_dirty)
        form.addRow("Длительность кроссфейда", self.crossfade_sec)

        self.fade_ms = QSpinBox()
        self.fade_ms.setRange(0, 3000)
        self.fade_ms.setSingleStep(50)
        self.fade_ms.setSuffix(" мс")
        self.fade_ms.setValue(self.settings.fade_ms)
        self.fade_ms.valueChanged.connect(self._mark_dirty)
        form.addRow("Fade in/out", self.fade_ms)

        self.silence_min = QSpinBox()
        self.silence_min.setRange(0, 3600)
        self.silence_min.setValue(self.settings.silence_min_sec)
        self.silence_min.valueChanged.connect(self._mark_dirty)
        form.addRow("Тишина между треками, мин", self.silence_min)

        self.silence_max = QSpinBox()
        self.silence_max.setRange(0, 3600)
        self.silence_max.setValue(self.settings.silence_max_sec)
        self.silence_max.valueChanged.connect(self._mark_dirty)
        form.addRow("Тишина между треками, макс", self.silence_max)

        self.ambient_pack = QLineEdit(self.settings.ambient_pack_name)
        self.ambient_pack.setToolTip(f"Пак с «атмосферой» (дождь, ветер, гул): {self.settings.ambient_pack_name}")
        self.ambient_pack.textChanged.connect(self._mark_dirty)
        form.addRow("Пак атмосферы", self.ambient_pack)

        self.duck_level = QDoubleSpinBox()
        self.duck_level.setRange(0.0, 1.0)
        self.duck_level.setSingleStep(0.05)
        self.duck_level.setValue(self.settings.duck_level)
        self.duck_level.setToolTip("Применяется с фазы 3, когда звук играет в другом приложении")
        self.duck_level.valueChanged.connect(self._mark_dirty)
        form.addRow("Порог ducking", self.duck_level)

        self.play_on_start = QCheckBox("Начинать воспроизведение при запуске")
        self.play_on_start.setChecked(self.settings.play_on_start)
        self.play_on_start.toggled.connect(self._mark_dirty)
        form.addRow("", self.play_on_start)

        self.start_minimized = QCheckBox("Запускать свёрнутым в трей")
        self.start_minimized.setChecked(self.settings.start_minimized)
        self.start_minimized.toggled.connect(self._mark_dirty)
        form.addRow("", self.start_minimized)

        self.close_to_tray = QCheckBox("Крестик сворачивает в трей, а не закрывает")
        self.close_to_tray.setChecked(self.settings.close_to_tray)
        self.close_to_tray.toggled.connect(self._mark_dirty)
        form.addRow("", self.close_to_tray)
        return box

    def _build_scheduler(self) -> QGroupBox:
        box = QGroupBox("Интеллектуальный выбор треков")
        form = QFormLayout(box)
        form.setSpacing(9)

        self.backend = QComboBox()
        for name in SchedulerFactory.names():
            self.backend.addItem(BACKEND_HINTS.get(name, name), name)
        index = self.backend.findData(self.settings.scheduler_backend)
        self.backend.setCurrentIndex(max(0, index))
        self.backend.currentIndexChanged.connect(self._mark_dirty)
        form.addRow("AI-бэкенд", self.backend)

        self.backend_note = QLabel(
            "Доступные бэкенды регистрируются через SchedulerFactory; переключение "
            "работает без перезапуска."
        )
        self.backend_note.setObjectName("hint")
        self.backend_note.setWordWrap(True)
        form.addRow("", self.backend_note)
        return box

    def _build_privacy(self) -> QGroupBox:
        box = QGroupBox("Приватность и логи")
        form = QFormLayout(box)
        form.setSpacing(9)

        self.log_level = QComboBox()
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self.log_level.addItem(level, level)
        index = self.log_level.findData(self.settings.log_level)
        self.log_level.setCurrentIndex(max(0, index))
        self.log_level.currentIndexChanged.connect(self._mark_dirty)
        form.addRow("Уровень логов", self.log_level)

        self.file_logging = QCheckBox("Писать логи на диск (хранятся 7 дней)")
        self.file_logging.setChecked(self.settings.file_logging)
        self.file_logging.toggled.connect(self._mark_dirty)
        form.addRow("", self.file_logging)

        privacy = QLabel(
            "Телеметрии нет. Логируются только агрегаты активности (keys_per_minute) и "
            "имя процесса для сопоставления с правилами; заголовки окон в БД не сохраняются."
        )
        privacy.setObjectName("hint")
        privacy.setWordWrap(True)
        form.addRow("", privacy)

        network = QLabel("Сетевой доступ используется только загрузчиком yt-dlp (фаза 2).")
        network.setObjectName("hint")
        network.setWordWrap(True)
        form.addRow("", network)
        return box

    def _build_paths(self) -> QGroupBox:
        box = QGroupBox("Файлы")
        form = QFormLayout(box)
        form.setSpacing(9)
        for caption, path in (
            ("Данные", self.service.paths.db),
            ("Библиотека", self.service.paths.library),
            ("Загрузки", self.service.paths.downloads),
            ("Логи", self.service.paths.logs),
        ):
            line = QLineEdit(str(path))
            line.setReadOnly(True)
            form.addRow(caption, line)
        return box

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 6, 0, 0)
        self.status = QLabel("Изменения применяются после «Сохранить»")
        self.status.setObjectName("hint")
        layout.addWidget(self.status)
        layout.addStretch()

        open_button = QPushButton("Открыть папку данных")
        open_button.setObjectName("ghost")
        open_button.clicked.connect(self._open_data_dir)
        layout.addWidget(open_button)

        reload_button = QPushButton("Отменить изменения")
        reload_button.setObjectName("ghost")
        reload_button.clicked.connect(self.load_values)
        layout.addWidget(reload_button)

        self.save_button = QPushButton("Сохранить")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        return bar

    # ------------------------------------------------------------------ logic

    def _mark_dirty(self, *_args: object) -> None:
        self._dirty = True
        self.status.setText("Есть несохранённые изменения")

    def load_values(self) -> None:
        settings = self.service.settings
        self.volume.setValue(settings.volume)
        self.shuffle.setChecked(settings.shuffle)
        self.crossfade.setChecked(settings.crossfade_enabled)
        self.crossfade_sec.setValue(settings.crossfade_sec)
        self.fade_ms.setValue(settings.fade_ms)
        self.silence_min.setValue(settings.silence_min_sec)
        self.silence_max.setValue(settings.silence_max_sec)
        self.ambient_pack.setText(settings.ambient_pack_name)
        self.duck_level.setValue(settings.duck_level)
        self.play_on_start.setChecked(settings.play_on_start)
        self.start_minimized.setChecked(settings.start_minimized)
        self.close_to_tray.setChecked(settings.close_to_tray)
        index = self.backend.findData(settings.scheduler_backend)
        self.backend.setCurrentIndex(max(0, index))
        level = self.log_level.findData(settings.log_level)
        self.log_level.setCurrentIndex(max(0, level))
        self.file_logging.setChecked(settings.file_logging)
        self._dirty = False
        self.status.setText("Изменений нет")

    def collect(self) -> dict[str, object]:
        return {
            "volume": self.volume.value(),
            "shuffle": self.shuffle.isChecked(),
            "crossfade_enabled": self.crossfade.isChecked(),
            "crossfade_sec": self.crossfade_sec.value(),
            "fade_ms": self.fade_ms.value(),
            "silence_min_sec": self.silence_min.value(),
            "silence_max_sec": self.silence_max.value(),
            "ambient_pack_name": self.ambient_pack.text().strip() or "Ambient Only",
            "duck_level": self.duck_level.value(),
            "play_on_start": self.play_on_start.isChecked(),
            "start_minimized": self.start_minimized.isChecked(),
            "close_to_tray": self.close_to_tray.isChecked(),
            "scheduler_backend": str(self.backend.currentData() or "random"),
            "log_level": str(self.log_level.currentData() or "INFO"),
            "file_logging": self.file_logging.isChecked(),
        }

    def save(self) -> None:
        values = self.collect()
        if values["silence_max_sec"] and int(values["silence_max_sec"]) < int(values["silence_min_sec"]):
            QMessageBox.warning(self, "Проверьте значения", "Максимум тишины не может быть меньше минимума")
            return
        for key, value in values.items():
            setattr(self.settings, key, value)
        self.service.apply_settings()
        try:
            target = save_settings(self.settings, self.service.paths)
        except OSError as exc:  # pragma: no cover - disk errors
            QMessageBox.critical(self, "Не удалось сохранить", str(exc))
            return
        self._dirty = False
        self.status.setText(f"Сохранено: {target}")

    def _open_data_dir(self) -> None:
        from ...win_util import open_path

        open_path(self.service.paths.root)

    @property
    def dirty(self) -> bool:
        return self._dirty
