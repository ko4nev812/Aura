"""Application configuration and data locations (ТЗ §5, §8).

All state lives in ``%APPDATA%/Aura`` — nothing leaves the machine.
Values can be overridden with a ``config.yaml`` in the data dir or with
``AURA_*`` environment variables.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

try:  # pragma: no cover - available in the pinned dependency set
    from pydantic_settings import YamlConfigSettingsSource
except Exception:  # pragma: no cover
    YamlConfigSettingsSource = None  # type: ignore[assignment]

APP_NAME = "Aura"
SUPPORTED_EXTENSIONS = (".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".wma")


def data_root() -> Path:
    override = os.environ.get("AURA_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


class AppPaths:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else data_root()

    @property
    def library(self) -> Path:
        return self.root / "library"

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def db(self) -> Path:
        return self.root / "aura.db"

    @property
    def config_file(self) -> Path:
        return self.root / "config.yaml"

    def ensure(self) -> "AppPaths":
        for directory in (self.root, self.library, self.downloads, self.logs):
            directory.mkdir(parents=True, exist_ok=True)
        return self


SchedulerBackend = Literal["random", "thompson", "epsilon_greedy", "lightgbm", "dqn"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AURA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    scheduler_backend: SchedulerBackend = "random"
    volume: int = Field(default=70, ge=0, le=100)
    crossfade_enabled: bool = True
    crossfade_sec: float = Field(default=2.0, ge=0.0, le=10.0)
    fade_ms: int = Field(default=400, ge=0, le=5000)
    silence_min_sec: int = Field(default=0, ge=0, le=3600)
    silence_max_sec: int = Field(default=0, ge=0, le=3600)
    ambient_pack_name: str = "Ambient Only"
    play_on_start: bool = True
    start_minimized: bool = False
    close_to_tray: bool = True
    shuffle: bool = True
    duck_level: float = Field(default=0.2, ge=0.0, le=1.0)
    log_level: str = "INFO"
    file_logging: bool = False
    library_subdir: str = "library"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        config_path = data_root() / "config.yaml"
        if YamlConfigSettingsSource is not None and config_path.exists():
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=config_path))
        sources.extend([dotenv_settings, file_secret_settings])
        return tuple(sources)


@lru_cache(maxsize=1)
def _cached_settings() -> tuple[AppPaths, Settings]:
    paths = AppPaths()
    return paths, Settings()


def load_settings(use_cache: bool = True) -> tuple[AppPaths, Settings]:
    """Return ``(paths, settings)``; ``use_cache=False`` re-reads config.yaml."""
    if use_cache:
        return _cached_settings()
    _cached_settings.cache_clear()
    return _cached_settings()


def save_settings(settings: Settings, paths: AppPaths) -> Path:
    """Persist editable settings to ``<data dir>/config.yaml`` and refresh cache."""
    import yaml

    payload = {key: getattr(settings, key) for key in type(settings).model_fields}
    paths.root.mkdir(parents=True, exist_ok=True)
    target = paths.config_file
    header = "# Aura settings — правится из окна настроек или вручную, перезапуск не нужен\n"
    body = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False)
    target.write_text(header + body, encoding="utf-8")
    _cached_settings.cache_clear()
    return target
