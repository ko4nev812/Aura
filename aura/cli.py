"""Command line entry point: ``python -m aura`` (GUI) и служебные подкоманды.

Подкоманды полезны для проверки каркаса без мыши: ``stats``, ``packs``,
``import``, ``toggle``, ``play`` (воспроизведение до Ctrl+C).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from .config import AppPaths, load_settings
from .log import get_logger

log = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aura",
        description="Aura — ambient-плеер, подбирающий музыку под вашу активность (фаза 1: каркас).",
    )
    parser.add_argument("--data-dir", help="каталог данных (по умолчанию %%APPDATA%%/Aura)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="запустить интерфейс (по умолчанию)")

    stats = sub.add_parser("stats", help="сводка по библиотеке")

    packs = sub.add_parser("packs", help="список паков и треков")
    packs.add_argument("--limit", type=int, default=20, help="треков на пак в выводе")

    imp = sub.add_parser("import", help="импорт папки с музыкой")
    imp.add_argument("path", help="папка с аудиофайлами")
    imp.add_argument("--pack", help="имя существующего или нового пака")
    imp.add_argument("--copy", action="store_true", help="скопировать файлы в библиотеку")

    toggle = sub.add_parser("toggle", help="включить/выключить пак или трек")
    toggle.add_argument("--pack", help="имя или id пака")
    toggle.add_argument("--track", help="id или часть названия трека")
    toggle.add_argument("--off", action="store_true", help="выключить вместо включения")

    play = sub.add_parser("play", help="проиграть трек без интерфейса (Ctrl+C — стоп)")
    play.add_argument("target", help="id трека, его название или путь к файлу")

    for command in (stats, packs, imp, toggle, play):
        command.set_defaults(uses_service=True)
    return parser


def _paths(args: argparse.Namespace) -> AppPaths:
    if args.data_dir:
        return AppPaths(Path(args.data_dir).expanduser()).ensure()
    return load_settings()[0]


def _service(args: argparse.Namespace):  # noqa: ANN202 - AuraService
    from .core.service import AuraService

    _defaults, settings = load_settings()
    return AuraService(paths=_paths(args), settings=settings)


def _configure_stdio(streams: Iterable[object] | None = None) -> None:
    """Консоль Windows по умолчанию cp1251/cp866 — без UTF-8 вывод падает на «→»."""
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - поток не перенастраивается
            pass


def command_stats(args: argparse.Namespace) -> int:
    service = _service(args)
    stats = service.library.stats()
    feedback = service.library.feedback_totals()
    print(f"Каталог данных: {service.paths.root}")
    print(f"Паков:            {stats['packs']}")
    print(f"Треков:           {stats['tracks']} (включено {stats['playable']})")
    print(f"Проанализировано: {stats['analyzed']}")
    print(f"Длительность:     {stats['duration_sec'] // 60} мин")
    print(f"Лайков/дизлайков: {feedback['likes']}/{feedback['dislikes']}")
    service.shutdown()
    return 0


def command_packs(args: argparse.Namespace) -> int:
    service = _service(args)
    packs = service.library.list_packs()
    if not packs:
        print("Библиотека пуста. Импортируйте папку: python -m aura import <путь>")
    for pack in packs:
        state = "вкл " if pack.enabled else "выкл"
        print(f"[{state}] {pack.name} ({pack.source}) — {pack.enabled_count}/{pack.track_count} треков")
        for track in pack.tracks[: args.limit]:
            flag = "•" if track.enabled and track.exists else "×"
            print(f"    {flag} {track.id[:8]}  {track.display_title}  [{_mm(track.duration_sec)}]")
    service.shutdown()
    return 0


def command_import(args: argparse.Namespace) -> int:
    service = _service(args)
    folder = Path(args.path).expanduser()
    if not folder.is_dir():
        print(f"Папка не найдена: {folder}", file=sys.stderr)
        return 2
    result = service.import_directory(
        folder, pack_name=args.pack, copy_files=args.copy
    )
    print(result.message)
    for line in result.errors:
        print(f"  ! {line}")
    for pack in service.library.list_packs():
        if pack.name == (args.pack or "") or args.pack is None:
            print(f"Пак: {pack.name} — {pack.track_count} треков")
    service.shutdown()
    return 0


def command_toggle(args: argparse.Namespace) -> int:
    service = _service(args)
    enabled = not args.off
    if args.pack:
        pack = service.library.find_pack_by_name(args.pack)
        if pack is None:
            pack = next((p for p in service.library.list_packs(with_tracks=False) if p.id == args.pack), None)
        if pack is None:
            print(f"Пак не найден: {args.pack}", file=sys.stderr)
            return 2
        service.library.set_pack_enabled(pack.id, enabled)
        print(f"Пак «{pack.name}» → {'включён' if enabled else 'выключен'}")
        service.shutdown()
        return 0

    needle = (args.track or "").lower()
    tracks = [t for t in service.library.list_tracks() if t.id == needle or needle in t.title.lower()]
    if not tracks:
        print(f"Трек не найден: {args.track}", file=sys.stderr)
        return 2
    if len(tracks) > 1:
        print("Слишком несколько совпадений, уточните id:")
        for track in tracks[:10]:
            print(f"  {track.id}  {track.display_title}")
        return 2
    track = tracks[0]
    service.library.set_track_enabled(track.id, enabled)
    print(f"Трек «{track.title}» → {'включён' if enabled else 'выключен'}")
    service.shutdown()
    return 0


def command_play(args: argparse.Namespace) -> int:
    """Проверка аудиодвижка без интерфейса: играет один трек до Ctrl+C."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from .app import create_app
    from .audio.engine import gain_from_percent

    service = _service(args)
    path = Path(args.target).expanduser()
    if path.is_file():
        file_path: str | None = str(path)
        title = path.stem
    else:
        needle = args.target.lower()
        match = next(
            (t for t in service.library.list_tracks(enabled_only=False) if t.id == needle or needle in t.title.lower()),
            None,
        )
        if match is None:
            print(f"Трек не найден: {args.target}", file=sys.stderr)
            return 2
        file_path, title = match.file_path, match.display_title

    app: QApplication = create_app([])
    engine = service.engine
    engine.set_volume(gain_from_percent(service.settings.volume))
    engine.load(file_path)
    print(f"▶ {title}", flush=True)

    def tick() -> None:
        snapshot = f"{engine.position_ms // 1000}s / {engine.duration_ms // 1000}s · {engine.state.value}"
        print(f"  {snapshot}", flush=True)

    timer = QTimer()
    timer.setInterval(5000)
    timer.timeout.connect(tick)
    timer.start()

    engine.error.connect(lambda message: (print(f"ошибка: {message}", file=sys.stderr), app.quit()))
    engine.track_finished.connect(app.quit)
    try:
        code = app.exec()
    except KeyboardInterrupt:  # pragma: no cover - manual only
        code = 0
    finally:
        engine.stop()
        service.shutdown()
    return code


def _mm(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


COMMANDS = {
    "stats": command_stats,
    "packs": command_packs,
    "import": command_import,
    "toggle": command_toggle,
    "play": command_play,
}


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "gui"

    if command == "gui":
        from .app import acquire_instance_lock, bootstrap

        lock = acquire_instance_lock()
        if lock is None:
            print("Aura уже запущена (см. значок в трее).", file=sys.stderr)
            return 3
        try:
            return bootstrap(data_dir=args.data_dir).exec()
        finally:
            lock.unlock()

    handler = COMMANDS[command]
    return handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
