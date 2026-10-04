# Aura

Фоновый плеер, который подбирает музыку под текущую работу. Реализована **фаза 1** из
[`docs/plan.md`](docs/plan.md): библиотека на SQLite, локальное воспроизведение с
плавными переходами, главное окно с пятью вкладками и системный трей.

Подробный отчёт о фазе 1 — [`docs/PHASE_1_REPORT.md`](docs/PHASE_1_REPORT.md).

Телеметрии нет: все данные лежат локально в `%APPDATA%/Aura/`.

---

## Возможности фазы 1

| Модуль | Состояние |
| --- | --- |
| SQLite-схема (паки, треки, анализ, правила, фидбек, play events, bandit arms) | готово |
| Library Manager: импорт папки/файлов, копирование, дедупликация, вкл/выкл, move | готово |
| Метаданные через `ffprobe` (длительность, битрейт, теги), фолбэк по имени файла | готово |
| Аудио-движок: play/pause/next/prev, два плеера, fade, crossfade, ducking, ambient-bed | готово |
| Пять вкладок UI: Сейчас играет, Библиотека, Правила, Аналитика, Настройки | готово |
| Трей: текущий трек, play/next/prev, лайк/дизлайк, mute, автоплей, список паков, выход | готово |
| Сворачивание в трей вместо закрытия, single-instance, горячие клавиши окна | готово |
| Feedback (лайк/дизлайк) и запись play events в БД | готово |
| Правила приложений: CRUD в UI, применение — в фазе 3 | частично |
| YouTube-импорт (yt-dlp) | фаза 2 |
| Анализ треков (BPM/energy/valence) | фаза 2 |
| Activity Monitor (окно, клавиатура, мышь) | фаза 3 |
| AI Scheduler (Thompson Sampling и др.) | фаза 4, есть только интерфейс и random-бэкенд |

---

## Требования

- Windows 10/11
- Python 3.11+ (проверено на 3.12)
- `ffprobe` в `PATH` — опционально, но без него длительность и формат берутся из имени файла

## Установка

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Зависимости: PyQt6, SQLAlchemy, pydantic-settings, PyYAML, psutil, pywin32.

## Запуск

```powershell
aura                       # GUI + трей
python -m aura             # то же самое
```

## CLI

```powershell
aura stats                                  # сводка по библиотеке
aura packs                                  # паки и треки
aura import "D:\Music\Focus" --copy        # импорт папки (копирование в библиотеку)
aura import "D:\Music\Focus" --pack Ambient # в существующий или новый пак
aura toggle --pack Ambient --off           # выключить пак
aura toggle --track "Slow Motion"          # переключить трек по id или подстроке
aura play "Slow Motion"                    # разовое воспроизведение без GUI
aura --data-dir "D:\AuraData" stats        # другой каталог данных
```

## Горячие клавиши (окно)

| Клавиши | Действие |
| --- | --- |
| `Ctrl+Alt+P` | play / pause |
| `Ctrl+Alt+→` / `Ctrl+Alt+←` | следующий / предыдущий трек |
| `Ctrl+Alt+L` / `Ctrl+Alt+D` | лайк / дизлайк |
| `Ctrl+Alt+M` | mute |
| `Ctrl+I` | импорт папки |
| `Ctrl+F` | поиск по библиотеке |

## Данные

```
%APPDATA%/Aura/
├── aura.db          # SQLite (WAL)
├── config.yaml      # настройки
├── library/         # файлы треков (при --copy)
├── downloads/       # заготовка под yt-dlp
└── logs/            # включается настройкой file_logging
```

Каталог данных переопределяется переменной `AURA_DATA_DIR` или флагом `--data-dir`.
Приоритет настроек: аргументы кода → переменные окружения (`AURA_*`) → `.env` →
`config.yaml` → значения по умолчанию.

---

## Структура кода

```
aura/
├── app.py            # QApplication, single-instance, сборка окна и трея
├── cli.py            # argparse-команды: stats/packs/import/toggle/play
├── config.py         # пути, Settings (pydantic-settings), сохранение YAML
├── db/               # Database (WAL, PRAGMA) + SQLAlchemy-модели
├── library/          # LibraryManager (CRUD, импорт, фидбек) + scanner (ffprobe)
├── audio/            # AudioEngine на QtMultimedia: fade, crossfade, duck
├── scheduler/        # интерфейс SchedulerBackend + random-реализация
├── core/             # PlaylistController (очередь, история, ambient) и AuraService
└── ui/               # MainWindow, TrayController, тема, виджеты, вкладки
```

Слои связаны так: UI → `AuraService` → `PlaylistController` + `AudioEngine` +
`LibraryManager` → `Database`. Планировщик подключается к сервису сменой бэкенда
(`AuraService.set_scheduler`), перезапуск приложения не нужен.

## Тесты

```powershell
$env:QT_QPA_PLATFORM="offscreen"
py -3.12 -m pytest
```

81 тестов: библиотека и БД, очередь и ambient-bed, реальный WAV-движок (fade,
crossfade), UI-вкладки и трей, конфигурация и CLI, а также сборка приложения целиком
(bootstrap, single-instance, выход через трей в отдельном процессе). Тест трея
пропускается, если окружение не даёт системный трей.

---

## Отличия от ТЗ (осознанные решения фазы 1)

- **Аудио: QtMultimedia (`QMediaPlayer`) вместо `sounddevice + pydub`.** Плееру нужен ровно
  один аудиопоток, а не два: второй `QMediaPlayer` со своим `QAudioOutput` держится в
  состоянии «готов», громкость поднимается по таймеру — это и есть fade/crossfade.
  Нет внешних декодеров и зависимости от устройства вывода по умолчанию.
- **SQLite через SQLAlchemy** вместо `sqlite3` — схема уже покрывает будущие фазы
  (анализ, правила, bandit arms), чтобы не мигрировать БД на этапе 2–4.
- **Полная схема создаётся сразу**, даже если часть таблиц пока не используется.
- **Превью очереди** строится из уже отобранных кандидатов и не повторяет треки; в
  режиме ожидания показывается подсказка вместо пустого списка.
- **Горячие клавиши только в окне** (`Ctrl+Alt+…`). Глобальные хоткеи требуют
  низкоуровневого хука и пока не реализованы.
- Файлы в библиотеке по умолчанию **не копируются** при импорте папки (только при
  `--copy`), чтобы не дублировать большие коллекции; БД хранит абсолютные пути.
- **Тесты не трогают реальные данные**: `AURA_DATA_DIR` на время прогона
  переопределяется на временный каталог, кэш `Settings` сбрасывается между тестами.
- **CLI переводит stdout/stderr в UTF-8** при старте: в консоли Windows с кодировкой
  cp1251/cp866 иначе падает вывод символа «→».