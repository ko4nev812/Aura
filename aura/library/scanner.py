"""Filesystem scanning and audio metadata probing (ТЗ §3.1, §3.2).

Metadata comes from ``ffprobe`` when available (ffmpeg is an optional external
dependency); otherwise we fall back to filename heuristics so that importing a
folder never fails.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import SUPPORTED_EXTENSIONS
from ..log import get_logger

log = get_logger("library.scanner")

_PROBE_TIMEOUT = 10.0
_TRACK_NUMBER = re.compile(r"^\s*(\d{1,3})\s*[-._)]\s*")
_ARTIST_TITLE = re.compile(r"^\s*(.+?)\s+[-–—]\s+(.+?)\s*$")


@dataclass(slots=True)
class AudioMeta:
    title: str
    artist: str | None = None
    duration_sec: int = 0
    format: str = ""
    file_size: int = 0


def is_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def iter_audio_files(root: Path, *, recursive: bool = True) -> list[Path]:
    """All playable files under ``root`` (skips hidden dirs and partial files)."""
    root = Path(root)
    if not root.exists():
        return []
    if root.is_file():
        return [root] if is_audio_file(root) else []

    globber = root.rglob if recursive else root.glob
    files: list[Path] = []
    for path in globber("*"):
        try:
            if not path.is_file():
                continue
            if path.name.startswith(".") or path.name.endswith((".part", ".crdownload", ".tmp")):
                continue
            if any(part.startswith(".") for part in path.parts):
                continue
            if is_audio_file(path):
                files.append(path)
        except OSError:  # pragma: no cover - broken symlink / permission
            continue
    files.sort(key=lambda p: str(p).lower())
    return files


def filename_meta(path: Path) -> AudioMeta:
    stem = path.stem
    stem = _TRACK_NUMBER.sub("", stem)
    match = _ARTIST_TITLE.match(stem)
    if match and len(match.group(1)) <= 80:
        artist, title = match.group(1).strip(), match.group(2).strip()
    else:
        artist, title = None, stem.strip()
    return AudioMeta(
        title=title or path.stem,
        artist=artist or None,
        format=path.suffix.lstrip(".").lower(),
        file_size=path.stat().st_size if path.exists() else 0,
    )


def probe(path: Path) -> AudioMeta:
    """Read duration/tags; never raises (falls back to filename heuristics)."""
    fallback = filename_meta(path)
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return fallback

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
            creationflags=_no_window_flag(),
        )
        payload = json.loads(completed.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.debug("ffprobe failed for %s: %s", path, exc)
        return fallback

    fmt = payload.get("format") or {}
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    streams = [s for s in (payload.get("streams") or []) if s.get("codec_type") == "audio"]
    stream_tags: dict[str, str] = {}
    if streams:
        stream_tags = {k.lower(): v for k, v in (streams[0].get("tags") or {}).items()}

    title = (stream_tags.get("title") or tags.get("title") or fallback.title or "").strip()
    artist = (
        stream_tags.get("artist")
        or tags.get("artist")
        or tags.get("album_artist")
        or fallback.artist
    )
    try:
        duration = int(round(float(fmt.get("duration") or 0)))
    except (TypeError, ValueError):
        duration = 0

    container = (fmt.get("format_name") or "").split(",")[0]
    codec = (streams[0].get("codec_name") if streams else "") or ""
    return AudioMeta(
        title=title or fallback.title,
        artist=(artist or None),
        duration_sec=duration,
        format=(codec or container or fallback.format or path.suffix.lstrip(".")).lower(),
        file_size=int(fmt.get("size") or fallback.file_size or 0),
    )


def copy_into_library(src: Path, library_dir: Path, *, pack_name: str) -> Path:
    """Copy ``src`` into ``library_dir/<pack>/``, keeping names unique."""
    library_dir = Path(library_dir)
    target_dir = library_dir / sanitize_component(pack_name)
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / _unique_name(src, target_dir)
    if not _same_file(src, target):
        shutil.copy2(src, target)
    return target


def sanitize_component(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "untitled"


def content_token(path: Path, size: int = 65536) -> str:
    """Cheap dedupe token: size + hash of the file head."""
    stat = path.stat()
    digest = hashlib.sha1()
    digest.update(str(stat.st_size).encode())
    with path.open("rb") as handle:
        handle.seek(0)
        digest.update(handle.read(size))
        handle.seek(max(0, stat.st_size - size))
        digest.update(handle.read(size))
    return digest.hexdigest()[:16]


def _unique_name(src: Path, target_dir: Path) -> str:
    candidate = sanitize_component(src.name)
    stem, suffix = Path(candidate).stem, Path(candidate).suffix
    if not (target_dir / candidate).exists():
        return candidate
    index = 2
    while True:
        name = f"{stem} ({index}){suffix}"
        if not (target_dir / name).exists():
            return name
        index += 1


def _same_file(src: Path, target: Path) -> bool:
    try:
        if not target.exists():
            return False
        if src.stat().st_size != target.stat().st_size:
            return False
        return content_token(src) == content_token(target)
    except OSError:  # pragma: no cover
        return False


def _no_window_flag() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0
