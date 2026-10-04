"""Small Win32 helpers used by the UI (Explorer, foreground window, taskbar)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .log import get_logger

log = get_logger("win")

IS_WINDOWS = sys.platform == "win32"


def open_path(target: str | Path) -> bool:
    """Open a file or folder with the default handler."""
    path = Path(target)
    if not path.exists():
        log.warning("open_path: %s does not exist", path)
        return False
    try:
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":  # pragma: no cover - not the target platform
            subprocess.Popen(["open", str(path)])
        else:  # pragma: no cover
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError as exc:
        log.warning("open_path failed for %s: %s", path, exc)
        return False


def reveal_in_explorer(file_path: str | Path) -> bool:
    """Select a file in Explorer (``explorer /select,<path>``)."""
    path = Path(file_path)
    if not IS_WINDOWS:
        return open_path(path.parent if path.exists() else path)
    if not path.exists():
        return open_path(path.parent)
    try:
        subprocess.Popen(
            ["explorer.exe", f"/select,{path}"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except OSError as exc:  # pragma: no cover
        log.warning("reveal failed: %s", exc)
        return False


def foreground_window() -> tuple[str | None, str]:
    """``(process_name, window_title)`` of the current foreground window.

    Used by the Activity Monitor (phase 3); phase 1 only asks for it to show the
    context badge, and it degrades to ``(None, '')`` off Windows.
    """
    if not IS_WINDOWS:  # pragma: no cover - non-target platform
        return None, ""
    try:
        import win32process  # type: ignore[import-not-found]
        import win32gui  # type: ignore[import-not-found]

        handle = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(handle) or ""
        _thread_id, process_id = win32process.GetWindowThreadProcessId(handle)
        import psutil

        name = psutil.Process(process_id).name()
        return name.lower(), title
    except Exception as exc:  # pragma: no cover - defensive: permissions, no session
        log.debug("foreground_window failed: %s", exc)
        return None, ""
