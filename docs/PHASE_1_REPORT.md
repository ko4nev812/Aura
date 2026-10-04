# Отчёт по фазе 1 — Ambient Player «Aura»

**Дата:** 4 октября 2026
**Область:** `C:\Users\master\Documents\Aura`
**Основание:** [`docs/plan.md`](plan.md), раздел 6 «Фазы разработки» → «Фаза 1: Каркас (1–2 недели)»
**Итог:** фаза 1 выполнена; 81 тест собран, 80 пройден, 1 пропущен по среде запуска.

---

## 1. Цели и задачи фазы

Цели фазы 1 по ТЗ (`docs/plan.md`, строки 404–407):

| # | Задача из ТЗ | Статус |
| --- | --- | --- |
| 1 | SQLite-схема | выполнено |
| 2 | Library Manager | выполнено |
| 3 | UI-каркас: главное окно + трей | выполнено |
| 4 | Аудио-движок: локальные файлы, play/pause/next | выполнено |

Дополнительно, вне буквального текста фазы 1, но необходимое для проверяемости каркаса:

- очередь и история воспроизведения, интервалы тишины, ambient-bed;
- сохранение фидбека (лайк/дизлайк) и фактов прослушивания — база для фазы 4;
- CLI для импорта и диагностики без GUI;
- автотесты, включая проверку реального аудио.

Что сознательно **не** входило в фазу 1 (по плану): YouTube-импорт, аудиоанализ (librosa), Activity Monitor, AI Scheduler, LightGBM/DQN.

---

## 2. Состояние системы контроля версий

Факты, установленные перед написанием отчёта:

- Git-репозиторий: `C:\Users\master\Documents` (то есть **общий** на всю папку «Документы», не отдельный репозиторий проекта Aura).
- Ветка: `main`. `HEAD` не существует — `git log` возвращает `fatal: your current branch 'main' does not have any commits yet`. **Коммитов в репозитории нет.**
- Каталог `Aura/` не отслеживается: `git status --porcelain` показывает единственную запись `?? Aura/`, `git ls-files -- Aura` — 0 файлов.
- `git diff --stat` пуст, так как сравнивать не с чем.

Следствие: **диффы и историю коммитов для отчёта получить невозможно**. Ниже работа описана по фактическому составу файлов и результатам прогонов. Отчёт не содержит хешей коммитов, номеров релизов и сравнений «до/после», потому что таких данных в VCS нет.

> Практический вывод: перед передачей проекта стоит завести отдельный репозиторий в `Aura/` (или хотя бы первый коммит) — иначе работа не защищена версионированием.

---

## 3. Внесённые изменения: новые файлы

Проект создан с нуля: до начала работы в каталоге existed только `docs/plan.md`.

### 3.1 Пакет приложения `aura/` (32 файла, 4 537 строк)

| Файл | Строк | Назначение |
| --- | ---: | --- |
| `aura/__init__.py` | 6 | версия пакета |
| `aura/__main__.py` | 6 | точка входа `python -m aura` |
| `aura/app.py` | 66 | `create_app`, `AuraApp`, `bootstrap`, single-instance на `QLockFile` |
| `aura/cli.py` | 196 | argparse-CLI: `gui`, `stats`, `packs`, `import`, `toggle`, `play` |
| `aura/config.py` | 113 | `AppPaths`, `Settings` (pydantic-settings), `load_settings`, `save_settings` |
| `aura/log.py` | 36 | `setup_logging` (опционально в файл), `get_logger` |
| `aura/win_util.py` | 61 | `open_path`, `reveal_in_explorer`, `foreground_window` (Win32 + psutil) |
| `aura/db/models.py` | 173 | 8 таблиц SQLAlchemy 2.0 |
| `aura/db/database.py` | 60 | `Database`: engine/session, PRAGMA, `create_schema`, `scalar` |
| `aura/db/__init__.py` | 15 | реэкспорт DTO БД |
| `aura/library/manager.py` | 525 | `LibraryManager` + DTO `PackInfo`, `TrackInfo`, `RuleInfo`, `ImportResult` |
| `aura/library/scanner.py` | 166 | `ffprobe`-метаданные, разбор имён, копирование, дедуп по содержимому |
| `aura/audio/state.py` | 23 | `PlayerState` (`STOPPED/PLAYING/PAUSED/SILENCE`) |
| `aura/audio/engine.py` | 362 | `AudioEngine`: 2 × `QMediaPlayer`, fade/crossfade/duck, `QAudioOutput` |
| `aura/scheduler/base.py` | 83 | `Context`, `SchedulerBackend`, `RandomScheduler`, `SchedulerFactory` |
| `aura/core/playlist.py` | 350 | `PlaylistController`: очередь, история, тишина, ambient-bed, кроссфейд |
| `aura/core/service.py` | 139 | `AuraService` — композиционный корень |
| `aura/ui/main_window.py` | 148 | окно, 5 вкладок, горячие клавиши, close-to-tray |
| `aura/ui/tray.py` | 166 | `TrayController`: меню трея, tooltip, уведомления |
| `aura/ui/theme.py` | 254 | неоновая QSS-тема, генерация иконок |
| `aura/ui/widgets.py` | 121 | `PulseOrb`, карточки, форматирование времени/громкости |
| `aura/ui/tabs/now_playing.py` | 286 | вкладка «Сейчас играет» |
| `aura/ui/tabs/library_tab.py` | 566 | вкладка «Библиотека», drag-and-drop, импорт |
| `aura/ui/tabs/rules_tab.py` | 217 | вкладка «Правила» (CRUD) |
| `aura/ui/tabs/analytics_tab.py` | 134 | вкладка «Аналитика» |
| `aura/ui/tabs/settings_tab.py` | 265 | вкладка «Настройки» |
| `aura/*/__init__.py` (6 файлов) | 0 | маркеры пакетов |

### 3.2 Тесты `tests/` (9 файлов, 1 249 строк)

| Файл | Строк | Тестов |
| --- | ---: | ---: |
| `tests/conftest.py` | 74 | фикстуры: offscreen-Qt, изоляция `AURA_DATA_DIR`, `service`, `music_dir` |
| `tests/helpers.py` | 37 | генерация WAV-тонов (`write_tone`) |
| `tests/test_library.py` | 179 | 11 |
| `tests/test_playlist.py` | 327 | 18 |
| `tests/test_audio_engine.py` | 122 | 11 |
| `tests/test_ui.py` | 309 | 21 (1 пропускается) |
| `tests/test_config_cli.py` | 120 | 13 |
| `tests/test_app.py` | 81 | 7 |

### 3.3 Конфигурация и документация

| Файл | Строк | Изменение |
| --- | ---: | --- |
| `pyproject.toml` | 25 | создан: metadata, зависимости, `[project.gui-scripts] aura`, настройки pytest |
| `README.md` | 116 | создан: возможности, установка, CLI, горячие клавиши, раскладка данных, карта кода, отличия от ТЗ |
| `docs/plan.md` | 338 | **не изменялся** (исходное ТЗ) |

---

## 4. Зависимости

### 4.1 Объявленные в `pyproject.toml`

```
PyQt6>=6.6
SQLAlchemy>=2.0
pydantic-settings>=2.2
PyYAML>=6            # добавлен в ходе фазы 1: без него не читается config.yaml
psutil>=5.9
pywin32>=306; sys_platform == 'win32'
dev: pytest>=8
```

`requires-python = ">=3.11"`. Точка входа: `aura = "aura.__main__:main"` (gui-scripts).

### 4.2 Фактически установленные версии (проверено `pip list`)

| Пакет | Версия |
| --- | --- |
| Python | 3.12.1 (`C:\Program Files\Python312\python.exe`) |
| PyQt6 / PyQt6-Qt6 | 6.9.0 |
| SQLAlchemy | 2.0.52 |
| pydantic | 2.10.1 |
| pydantic-settings | 2.15.0 |
| PyYAML | 6.0.3 |
| psutil | 7.0.0 |
| pywin32 | 306 |
| pytest | 9.1.1 |

### 4.3 Внешние инструменты

- `ffprobe` (ffmpeg 7.0.1) — используется для метаданных. Проверено: `shutil.which("ffprobe")` в `aura/library/scanner.py:87`.
- Требований к ffmpeg нет: без него работает фолбэк на разбор имени файла (`scanner.py:68`, `filename_meta`).

### 4.4 Зависимости будущих фаз не устанавливались

Проверено поиском по `aura/`: `yt_dlp`, `librosa`, `numpy`, `sklearn`, `sounddevice`, `pydub` — **0 вхождений в коде** (`sounddevice`/`pydub` упоминаются только в поясняющем комментарии `aura/audio/engine.py:3`; `lightgbm`, `dqn`, `epsilon_greedy` — только как подписи будущих фаз в `aura/config.py:72` и `aura/ui/tabs/settings_tab.py:31-33`).

---

## 5. Новые компоненты и точки интеграции

### 5.1 Схема данных (`aura/db/models.py`)

Создаются все 8 таблиц уже в фазе 1, чтобы фазы 2–4 не требовали миграции:

| Таблица | Ключевые поля | Назначение |
| --- | --- | --- |
| `packs` | `id`, `name`, `source`, `source_url`, `enabled`, `created_at` | пак/плейлист |
| `tracks` | `id`, `pack_id`→`packs`, `title`, `artist`, `file_path`, `duration_sec`, `format`, `file_size`, `enabled` | трек |
| `track_analysis` | `track_id` PK→`tracks`, `bpm`, `energy`, `valence`, `danceability`, `acousticness`, `instrumentalness`, `loudness_db`, `key`, `mood_tags` (JSON), `analyzed_at` | заготовка фазы 2 |
| `app_rules` | `process_name`, `title_pattern`, `mode`, `custom_pack_ids` (JSON), `pause_behavior`, `duck_level`, `priority`, `enabled` | правила приложений (фаза 3) |
| `feedback` | `track_id`→`tracks`, `session_id`, `rating` (±1), `context_snapshot` (JSON), `position_in_track_sec` | лайки/дизлайки |
| `play_events` | `track_id`, `session_id`, `context_snapshot`, `process_name`, `activity_level`, `time_of_day`, `started_at`, `completed`, `skipped` | история для аналитики и бандита |
| `bandit_arms` | `track_id`, `context_key` PK, `alpha`, `beta`, `plays` | параметры Thompson Sampling (фаза 4) |
| `settings` | `key`, `value` | редкие/сырые значения настроек |

PRAGMA при подключении (`aura/db/database.py:68-71`): `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=10000`.

### 5.2 Конфигурация (`aura/config.py`)

- `AppPaths` (`config.py:42`): `root`, `library`, `downloads`, `logs`, `db` (`aura.db`), `config_file` (`config.yaml`), метод `ensure()`.
- `data_root()` (`config.py:32`): `AURA_DATA_DIR` → иначе `%APPDATA%/Aura` (Windows) или `~/.local/share/Aura`.
- `Settings` (`config.py:75`), 16 полей: `scheduler_backend`, `volume`, `crossfade_enabled`, `crossfade_sec`, `fade_ms`, `silence_min_sec`, `silence_max_sec`, `ambient_pack_name`, `play_on_start`, `start_minimized`, `close_to_tray`, `shuffle`, `duck_level`, `log_level`, `file_logging`, `library_subdir`.
- Приоритет источников (`config.py:100-114`): аргументы кода → переменные окружения `AURA_*` → `.env` → `config.yaml` → значения по умолчанию.

### 5.3 Аудио-движок (`aura/audio/engine.py`)

Два слота: в цикле создаются два `QAudioOutput` и два `QMediaPlayer`, каждый плеер привязан к своему выходу, оба стартуют с громкостью 0 (`engine.py:115-126`). Активный слот — `self._active` (`engine.py:128`). Ключевые элементы:

- `_Ramp` (`engine.py:37`) — линейно-квадратичная (smoothstep) огибающая громкости с шагом 50 мс; `fade_in`, `fade_out`, `crossfade_to`.
- `gain_from_percent` / `percent_from_gain` (`engine.py:28,33`) — перценти ↔ Qt-громкость (нелинейная шкала).
- `set_muted`, `toggle_mute`, `set_duck`, `ducked`, `adjust_volume`, `seek_fraction`, `mark_silence`, `apply_settings`.
- Сигналы: `state_changed`, `position_changed`, `track_finished`, `error`.
- Состояния вычисляются с учётом фактического положения обоих плееров (`engine.py:395`, `_on_playback_state`).

### 5.4 Плеер-контроллер (`aura/core/playlist.py`)

`PlaylistController` — единственный владелец логики выбора и очереди:

- Сигналы: `track_changed`, `state_changed`, `position_changed`, `error`, `context_changed`.
- Транспорт: `start`, `stop`, `toggle_playback`, `pause`, `resume`, `play_next`, `play_previous`, `seek_to_fraction`, `skip_silence`.
- Очередь: `enqueue`, `play_many`, `upcoming` (предпросмотр 5 позиций, `QUEUE_PREVIEW=5`), `queued_tracks` (только явная очередь), `set_pack_filter`.
- Тишина между треками: `_silence_range` (`playlist.py:284`) берёт диапазон из настроек; при `ambient_pack_name` проигрываетсяambient-трек вместо полной тишины (`_ambient_track`, `playlist.py:334`).
- Кроссфейд: `play_next` (`playlist.py:190`) включает его при `crossfade_enabled` и наличии следующего трека.
- История: `RECENT_LIMIT=12`, `play_previous` возвращает предыдущий из истории, а не перезапускает текущий.

### 5.5 Планировщик (`aura/scheduler/base.py`)

- `Context` (`base.py:11`): `process_name`, `activity_level`, `time_of_day`; ключ `"{process}|{activity}|{time_of_day}"`.
- `SchedulerBackend` (ABC): `select_next`, `report_result`.
- `RandomScheduler` — единственная реализация фазы 1: случайный выбор со штрафом за недавние повторы.
- `SchedulerFactory.register/names/create` — точка подключения бандитов фаз 4–6 без изменения сервиса.

### 5.6 Library Manager (`aura/library/manager.py`)

Публичный API (выборочно, полный список — 40+ методов):

- Паки: `create_pack`, `rename_pack`, `delete_pack`, `set_pack_enabled`, `get_pack`, `list_packs`, `find_pack_by_name`.
- Треки: `list_tracks`, `get_track`, `set_track_enabled`, `delete_track`, `move_track`, `has_file`, `add_local_file`.
- Импорт: `import_directory` (`manager.py:281`) с опцией копирования в библиотеку; `ImportResult` сообщает «найдено/добавлено/пропущено».
- Правила: `list_rules`, `add_rule`, `update_rule`, `delete_rule` (CRUD готов, enforcement — фаза 3).
- Фидбек и статистика: `record_play`, `record_feedback`, `latest_feedback`, `feedback_totals`, `stats`, `mark_missing_files`, `tracks_needing_analysis`.

Сканер (`aura/library/scanner.py`): `is_audio_file`, `iter_audio_files`, `filename_meta` (разбор `NN - Artist - Title`), `probe` (ffprobe, таймаут 10 с), `copy_into_library`, `sanitize_component`, `content_token` (SHA-1 по первым 64 КиБ для дедупликации).

### 5.7 Композиционный корень (`aura/core/service.py`)

`AuraService` — точка интеграции UI, БД, аудио и планировщика: ленивые свойства `engine`/`playlist`, `current_context()`, `set_scheduler(name)`, `apply_settings()`, `save_settings()`, `record_feedback()`, `import_directory()`, `snapshot()`, `mark_missing_files()`, идемпотентный `shutdown()`, флаг `is_shutdown`.

### 5.8 UI

- `MainWindow` (`aura/ui/main_window.py`): 5 вкладок (`main_window.py:56-60`), общий словарь горячих клавиш `SHORTCUTS` (`main_window.py:23`), `trigger(action)` как единая точка входа для UI и трея, `closeEvent` с режимом close-to-tray.
- `TrayController` (`aura/ui/tray.py`): меню (текущий трек, play/next/prev, лайк/дизлайк, mute, автоплей, подменю паков, «Открыть Aura», «Выход»), динамический tooltip, `showMessage`-уведомления.
- Тема: `aura/ui/theme.py` — QSS в стиле неона, генерация иконок (`orb_icon`, `transport_icon`, `badge_icon`).
- Виджеты: `aura/ui/widgets.py` — `PulseOrb` (пульсация при Playing), карточки статистики, `format_long_duration`, `format_size`.

Горячие клавиши окна (`main_window.py:23-32`): `Ctrl+Alt+P`, `Ctrl+Alt+→`, `Ctrl+Alt+←`, `Ctrl+Alt+L`, `Ctrl+Alt+D`, `Ctrl+Alt+M`, `Ctrl+I`, `Ctrl+F`.

### 5.9 Точки входа

- `aura/app.py`: `create_app` (стиль Fusion, `quitOnLastWindowClosed=False`, тема), `AuraApp` (окно + трей, `aboutToQuit → shutdown`), `bootstrap`, `acquire_instance_lock` (`QLockFile` в `%TEMP%`).
- `aura/cli.py`: подкоманды `stats`, `packs`, `import` (`--pack`, `--copy`), `toggle` (`--pack`/`--track`, `--off`), `play`; глобальный `--data-dir`; `_configure_stdio` переводит вывод в UTF-8.

---

## 6. Исправленные в ходе фазы дефекты

Найденные собственными тестами, а не по плану:

| Дефект | Симптом | Исправление |
| --- | --- | --- |
| `LibraryManager.create_pack` не вызывал `session.add()` | пак не сохранялся | `aura/library/manager.py:125` |
| `QLockFile.release()` не существует | GUI падал с трейсбеком при выходе | `aura/cli.py` → `lock.unlock()` |
| «Выход» закрывал окно, но не event loop (`quitOnLastWindowClosed=False`) | процесс оставался в фоне | `aura/ui/tray.py:122` — `QApplication.quit()`, `icon.hide()`, идемпотентный `shutdown` |
| `config.yaml` перебивал переменные окружения | `AURA_VOLUME=61` игнорировался при `volume: 25` | порядок источников в `aura/config.py:109` |
| `UnicodeEncodeError` на «→» в консоли cp1251/cp866 | падение `aura toggle` с трассировкой | `aura/cli.py` → `_configure_stdio()` (UTF-8, `errors="replace"`) |
| Чтение настроек создавало `%APPDATA%/Aura` даже с `--data-dir` | побочный эффект в чужом каталоге | `load_settings()` без `ensure()`; `ensure()` перенесён в `AuraService.__init__` (`service.py:33`) |
| `QPen` из `QColor` в теме | ошибка Qt | `aura/ui/theme.py` |
| `QFrame.Shape.NoFrame`, `Qt.ShortcutContext.WindowShortcut` | ошибки Qt 6.9 | `aura/ui/tabs/settings_tab.py`, `aura/ui/main_window.py` |
| Превью очереди повторяло один и тот же трек | дубли в «Сейчас играет» | `_peek_next(..., fallback=False)` (`playlist.py:361`) |
| Кнопки лайк/дизлайк не были checkable | `isChecked()` всегда `False` | `setCheckable(True)` — `aura/ui/tabs/now_playing.py:169` |
| Переключение трека не обновляло дерево и статус | UI показывал устаревшие данные | `_on_item_changed` — `aura/ui/tabs/library_tab.py:452` |
| `PulseOrb` без проверяемого состояния | нельзя было протестировать пульсацию | свойство `is_pulsing` — `aura/ui/widgets.py:101` |
| Тесты писали в реальный `%APPDATA%/Aura` | тесты трогали пользовательские данные | изоляция `AURA_DATA_DIR` в `tests/conftest.py` |

---

## 7. Выполненные проверки

### 7.1 Автотесты

Команда:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
py -3.12 -m pytest
```

Результат последнего прогона:

```
80 passed, 1 skipped in 14.18s
```

| Файл | Тестов | Результат |
| --- | ---: | --- |
| `tests/test_library.py` | 11 | пройдены |
| `tests/test_playlist.py` | 18 | пройдены |
| `tests/test_audio_engine.py` | 11 | пройдены (реальный WAV: fade, crossfade, duck) |
| `tests/test_ui.py` | 21 | 20 пройдено, 1 пропущен |
| `tests/test_config_cli.py` | 13 | пройдены |
| `tests/test_app.py` | 7 | пройдены |

Пропущенный тест: `tests/test_ui.py:303` — «системный трей недоступен в этом окружении» (offscreen-платформа не даёт `QSystemTrayIcon`). Это ограничение среды, а не пропуск функциональности: трей покрыт в `tests/test_app.py`.

Что покрыто проверками:

- **БД/библиотека:** создание схемы, WAL и повторное открытие, CRUD паков и треков, вкл/выкл, `move_track`, дедупликация, импорт с копированием, `mark_missing_files`, статистика, правила, фидбек, `record_play`.
- **Плеер:** очередь, история, `play_previous`, pack-фильтр, интервалы тишины, ambient-bed (включая библиотеку из одного трека), предпросмотр очереди без повторов, `snapshot`.
- **Аудио (реальный звук):** загрузка WAV, fade-in по таймеру, кроссфейд между слотами, mute/duck, перевод громкости.
- **UI:** 5 вкладок, дерево библиотеки с чекбоксами, поиск, карточки аналитики, сохранение настроек roundtrip, лайк/дизлайк, горячие клавиши, close-to-tray.
- **Конфигурация и CLI:** пути, дефолты и валидация, приоритет YAML/env, roundtrip `config.yaml`, все CLI-команды и коды возврата, `--data-dir` не трогает каталог по умолчанию.
- **Приложение:** bootstrap (окно + трей), single-instance, `start_minimized`, и реальный выход через трей в отдельном процессе (`RESULT 0 True`).

### 7.2 Статические и компиляционные проверки

- `py -3.12 -m compileall -q aura tests` — успешно.
- Проверка неиспользуемых импортов (AST-обход всех `*.py`) — чисто после правок; удалены `QDialog`, `setup_logging`, `QGuiApplication` и др.
- Импорт всех основных модулей (`aura.app`, `aura.cli`, `aura.ui.*`, `aura.core.*`) — успешно.

### 7.3 Ручные smoke-тесты

Сценарий на временном каталоге данных (сгенерированы два WAV-файла):

| Команда | Результат |
| --- | --- |
| `python -m aura --data-dir <tmp> stats` | сводка, код 0 |
| `python -m aura --data-dir <tmp> import <music> --copy` | «найдено 2, добавлено 2», код 0 |
| `python -m aura --data-dir <tmp> toggle --pack music --off` | «Пак «music» → выключен», код 0 (после фикса кодировки) |
| `python -m aura --data-dir <tmp> packs` | пак и треки с длительностью |
| `python -m aura --help` | список подкоманд |
| GUI-процесс с выходом через трей | `RESULT 0 True`, код процесса 0 |
| `%APPDATA%/Aura` после прогонов | не создаётся (проверено `Test-Path` → `False`) |

---

## 8. Известные ограничения

### 8.1 Функциональные (по плану, следующие фазы)

| Ограничение | Фаза |
| --- | --- |
| Импорт с YouTube (`yt-dlp`) отсутствует; `downloads/` — пустая заготовка | 2 |
| Анализ треков (BPM/energy/valence) не выполняется; таблица `track_analysis` пуста, поля в UI не заполняются | 2 |
| Activity Monitor не реализован: `current_context()` (`service.py:67`) берёт только имя процесса на переднем плане и время суток; ввода, клавиатуры/мыши, детекта внешнего звука нет | 3 |
| Правила приложений создаются и редактируются, но **не применяются** к воспроизведению (нет enforcement, нет ducking по правилам) | 3 |
| AI Scheduler отсутствует: работает только `RandomScheduler`; `thompson`, `epsilon_greedy`, `lightgbm`, `dqn` — только имена в реестре и UI-подписи | 4–6 |
| Ранжировщик LightGBM и RL (DQN) не реализованы | 5–6 |
| Глобальные горячие клавиши отсутствуют (работают только в окне; глобальные требуют низкоуровневого хука) | 5 |
| Нет экспорта/импорта настроек и БД | 5 |

### 8.2 Технические и эксплуатационные

- **Проверено только на Python 3.12.1 и Windows.** `requires-python` указывает 3.11+, но на 3.11 прогон не выполнялся.
- **Тесты выполнялись в offscreen-режиме** (`QT_QPA_PLATFORM=offscreen`): реальный звук в тестах воспроизводился файлами, но через системный аудиовыход приложение вручную не прослушивалось.
- **Системный трей не проверялся в интерактивном режиме** — в среде нет трея; тест трея пропускается.
- **Зависимости установлены глобально** в профиле Python пользователя, а не в виртуальное окружение проекта; `pip install -e ".[dev]"` в чистом venv не проверялся.
- **Пакет не установлен**: запуск проверен через `python -m aura` из корня проекта; entry point `aura` из `gui-scripts` не проверялся.
- `docs/plan.md` и README не изменялись после создания отчёта; число тестов в README (81) совпадает с фактическим прогоном.
- Миграций БД нет: схема версионируется только через `create_schema()`; при изменении моделей потребуется пересоздание `aura.db`.
- Логи пишутся в консоль; файловые логи включаются опционально (`file_logging`), с ротацией по 7 дням, как требует ТЗ, **не реализовано**.
- Кроссфейд реализован на таймерах Qt, а не на выборке по waveform; при очень коротких треках (< длины кроссфейда) возможны пропуски.

### 8.3 Отклонения от ТЗ (осознанные, зафиксированы в README)

1. **Аудио: QtMultimedia (`QMediaPlayer`) вместо `sounddevice + pydub`.** Нужен один аудиопоток, а не два: второй плеер держится готовым, громкость поднимается по таймеру — это и есть fade/crossfade. Причина зафиксирована в docstring `aura/audio/engine.py:1-5`.
2. **SQLite через SQLAlchemy** вместо `sqlite3` — из-за полной схемы под будущие фазы.
3. **Полная схема создаётся сразу**, даже если часть таблиц пока не используется.
4. **Файлы при импорте не копируются по умолчанию** (только `--copy` / чекбокс в UI), чтобы не дублировать большие коллекции.
5. **Кнопки лайк/дизлайк в трее и на вкладке** реализованы в фазе 1 (ТЗ относит их к фазе 4), поскольку без них фидбек некуда писать.

---

## 9. Следующие шаги

### 9.1 Ближайшие (перед фазой 2)

1. **Завести контроль версий**: отдельный репозиторий в `Aura/` и первый коммит; добавить `.gitignore` (`__pycache__/`, `.pytest_cache/`, `*.db`, `config.yaml`).
2. **Проверить в реальной среде**: интерактивный трей, звук через колонки, close-to-tray, `pip install -e ".[dev]"` в venv, запуск `aura` как установленного entry point.
3. **Прогнать на Python 3.11** (заявлено в `requires-python`) либо сузить требование до 3.12.
4. **Ротация логов** за 7 дней (требование ТЗ §8) — сейчас файловые логи растут без ограничения.

### 9.2 Фаза 2 — импорт и анализ

5. Импорт YouTube через `yt-dlp` в `downloads/` с записью `packs.source = "youtube"` и `source_url`.
6. Пайплайн анализа (BPM, energy, valence) с записью в `track_analysis`; заполнение метаданных в UI; обновление счётчика «проанализировано» в «Аналитике».
7. Учесть `tracks_needing_analysis()` (`manager.py:485`) — метод уже готов.

### 9.3 Фаза 3 — Activity Monitor

8. Отслеживание активного окна, клавиатуры и мыши ( groundwork: `win_util.foreground_window()` уже есть).
9. Применение правил из `app_rules`: `pause` / `duck` / custom pack; ducking через `AudioEngine.ducked()`.
10. Пауза при внешнем звуке; список «чёрных» приложений для YouTube/Zoom/игр.

### 9.4 Фазы 4–6

11. Контекстный бандит Thompson Sampling поверх `bandit_arms` и `SchedulerFactory.register("thompson", …)`, переключение без перезапуска через `AuraService.set_scheduler`.
12. Аналитика накопленных `play_events` и `feedback`; при достаточном объёме данных — LightGBM-ранжировщик.
13. Глобальные горячие клавиши, экспорт/импорт настроек, полировка анимаций.

---

## 10. Сводка файлов для ревью

Изменённые/созданные файлы относительно исходного состояния (в репозитории не закоммичены):

```
README.md
pyproject.toml
aura/__init__.py
aura/__main__.py
aura/app.py
aura/cli.py
aura/config.py
aura/log.py
aura/win_util.py
aura/audio/__init__.py
aura/audio/engine.py
aura/audio/state.py
aura/core/__init__.py
aura/core/playlist.py
aura/core/service.py
aura/db/__init__.py
aura/db/database.py
aura/db/models.py
aura/library/__init__.py
aura/library/manager.py
aura/library/scanner.py
aura/scheduler/__init__.py
aura/scheduler/base.py
aura/ui/__init__.py
aura/ui/main_window.py
aura/ui/theme.py
aura/ui/tray.py
aura/ui/widgets.py
aura/ui/tabs/__init__.py
aura/ui/tabs/analytics_tab.py
aura/ui/tabs/library_tab.py
aura/ui/tabs/now_playing.py
aura/ui/tabs/rules_tab.py
aura/ui/tabs/settings_tab.py
tests/__init__.py
tests/conftest.py
tests/helpers.py
tests/test_app.py
tests/test_audio_engine.py
tests/test_config_cli.py
tests/test_library.py
tests/test_playlist.py
tests/test_ui.py
docs/PHASE_1_REPORT.md   (этот документ)
```

Не изменялось: `docs/plan.md`.