"""Фаза 1: конфигурация (YAML/env) и CLI-подкоманды."""

from __future__ import annotations

import pytest

from aura import cli
from aura.config import AppPaths, Settings, data_root, save_settings
from aura.db.database import Database


def test_app_paths_layout(tmp_path):
    paths = AppPaths(tmp_path / "Aura").ensure()
    assert paths.root == tmp_path / "Aura"
    assert paths.library.exists() and paths.downloads.exists() and paths.logs.exists()
    assert paths.db == paths.root / "aura.db"
    assert paths.config_file == paths.root / "config.yaml"


def test_data_root_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AURA_DATA_DIR", str(tmp_path / "custom"))
    assert data_root() == (tmp_path / "custom").resolve()


def test_settings_defaults_and_validation():
    settings = Settings()
    assert settings.volume == 70 and settings.crossfade_sec == 2.0
    assert settings.log_level == "INFO" and settings.file_logging is False
    assert settings.ambient_pack_name == "Ambient Only"
    assert settings.library_subdir == "library"
    with pytest.raises(Exception):
        Settings(volume=200)


def test_settings_yaml_overrides(tmp_path, monkeypatch):
    root = tmp_path / "AuraData"
    (root / "library").mkdir(parents=True)
    (root / "config.yaml").write_text(
        "volume: 25\nshuffle: false\nscheduler_backend: thompson\ncrossfade_sec: 4.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AURA_DATA_DIR", str(root))
    from aura.config import load_settings

    load_settings(use_cache=False)
    _paths, settings = load_settings()
    assert settings.volume == 25
    assert settings.shuffle is False
    assert settings.scheduler_backend == "thompson"
    assert settings.crossfade_sec == pytest.approx(4.5)


def test_env_overrides_yaml(tmp_path, monkeypatch):
    root = tmp_path / "AuraData"
    root.mkdir()
    (root / "config.yaml").write_text("volume: 25\n", encoding="utf-8")
    monkeypatch.setenv("AURA_DATA_DIR", str(root))
    monkeypatch.setenv("AURA_VOLUME", "61")
    from aura.config import load_settings

    load_settings(use_cache=False)
    _paths, settings = load_settings()
    assert settings.volume == 61  # env важнее config.yaml


def test_save_settings_roundtrip(tmp_path):
    paths = AppPaths(tmp_path / "Aura").ensure()
    settings = Settings(volume=42, silence_max_sec=30, ambient_pack_name="Dozhd")
    target = save_settings(settings, paths)
    text = target.read_text(encoding="utf-8")
    assert "volume: 42" in text and "ambient_pack_name: Dozhd" in text
    assert "scheduler_backend" in text and "silence_max_sec: 30" in text
    assert target == paths.config_file


def test_wal_mode_survives_reopen(tmp_path):
    from aura.db.models import Pack

    db = Database(tmp_path / "aura.db")
    db.create_schema()
    with db.session() as session:
        session.add(Pack(name="Persisted", source="local"))
    db.close()

    again = Database(tmp_path / "aura.db")
    with again.new_session() as session:
        names = [row[0] for row in session.query(Pack.name).all()]
    assert names == ["Persisted"]
    journal = str(again.scalar("PRAGMA journal_mode")).lower()
    again.close()
    assert journal == "wal"


def test_cli_stats_and_packs(service, music_dir, capsys):  # noqa: ARG001
    service.import_directory(music_dir)
    service_db = str(service.paths.root)

    assert cli.main(["--data-dir", service_db, "stats"]) == 0
    out = capsys.readouterr().out
    assert "Паков:            1" in out
    assert "Треков:           3" in out

    assert cli.main(["--data-dir", service_db, "packs"]) == 0
    out = capsys.readouterr().out
    assert "music" in out and "Slow Motion" in out


def test_cli_import_toggle_and_errors(service, music_dir, capsys, tmp_path):  # noqa: ARG001
    root = str(service.paths.root)
    assert cli.main(["--data-dir", root, "import", music_dir, "--pack", "From CLI"]) == 0
    out = capsys.readouterr().out
    assert "добавлено 3" in out

    assert cli.main(["--data-dir", root, "toggle", "--pack", "From CLI", "--off"]) == 0
    assert "выключен" in capsys.readouterr().out

    assert cli.main(["--data-dir", root, "toggle", "--pack", "нет такого"]) == 2
    assert cli.main(["--data-dir", root, "import", str(tmp_path / "absent")]) == 2

    from aura.config import load_settings

    load_settings(use_cache=False)


def test_cli_toggle_track_by_name(service, music_dir, capsys):  # noqa: ARG001
    root = str(service.paths.root)
    cli.main(["--data-dir", root, "import", music_dir])
    capsys.readouterr()
    assert cli.main(["--data-dir", root, "toggle", "--track", "Driven", "--off"]) == 0
    assert "выключен" in capsys.readouterr().out
    assert cli.main(["--data-dir", root, "toggle", "--track", "Driven"]) == 0
    assert "включён" in capsys.readouterr().out
    assert cli.main(["--data-dir", root, "toggle", "--track", "нет-такого"]) == 2


def test_cli_parser_has_subcommands():
    parser = cli.build_parser()
    args = parser.parse_args(["--data-dir", "x", "import", "y", "--copy"])
    assert args.command == "import" and args.copy is True
    assert parser.parse_args(["stats"]).command == "stats"
    assert parser.parse_args([]).command is None


def test_cli_data_dir_does_not_touch_default_root(tmp_path, monkeypatch, capsys):  # noqa: ARG001
    default_root = tmp_path / "DefaultRoot"
    monkeypatch.setenv("AURA_DATA_DIR", str(default_root))
    target = tmp_path / "CustomRoot"

    assert cli.main(["--data-dir", str(target), "stats"]) == 0
    assert (target / "aura.db").exists()
    assert not default_root.exists(), "чтение настроек не должно создавать каталог по умолчанию"


def test_configure_stdio_survives_non_reconfigurable_stream():
    class FakeStream:
        pass

    class BrokenStream:
        def reconfigure(self, **_kwargs):  # noqa: ANN003, ANN202
            raise OSError("поток закрыт")

    cli._configure_stdio([FakeStream(), BrokenStream()])
