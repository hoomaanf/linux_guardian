"""Detect leftover config/cache/data directories belonging to applications
that are no longer installed.

Heuristic (deliberately conservative — false negatives are fine, false
positives are not):

For each subdirectory under the watched roots (~/.config, ~/.cache,
~/.local/share, ~/.local/state, ~/.var/app), the directory "belongs" to an
app if we can match its name to something we currently believe is
installed: a binary on PATH, a .desktop launcher, or a Flatpak/Snap app ID.
If NONE of those match, it's flagged NEEDS_CONFIRMATION as a possible
leftover — never SAFE, because name-matching heuristics can miss unusual
binary names, and the user must always confirm before anything is removed.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from app.cleaner.models import Finding, RiskLevel, ScanResult
from app.core.logging_config import get_logger

logger = get_logger("scanner.leftover")

_WATCHED_ROOTS = [
    "~/.config",
    "~/.cache",
    "~/.local/share",
    "~/.local/state",
    "~/.mozilla",
    "~/.var/app",
]

_DESKTOP_ENTRY_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    "~/.local/share/applications",
]

# Directories that are never app-specific and should never be flagged.
_IGNORE_NAMES = {
    "fontconfig", "mime", "systemd", "dconf", "gtk-3.0", "gtk-4.0",
    "icon-theme.cache", "recently-used.xbel", "user-dirs.dirs",
    "user-dirs.locale", "pulse", "pipewire", "dbus-1", "keyrings",
    "gvfs-metadata", "evolution", "nautilus", "baloo", "akonadi",
}


def _installed_binary_names() -> set[str]:
    names: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        try:
            for entry in os.scandir(directory):
                names.add(entry.name.lower())
        except OSError:
            continue
    return names


def _installed_desktop_app_ids() -> set[str]:
    ids: set[str] = set()
    for template in _DESKTOP_ENTRY_DIRS:
        directory = Path(os.path.expanduser(template))
        if not directory.exists():
            continue
        try:
            for entry in directory.glob("*.desktop"):
                ids.add(entry.stem.lower())
        except OSError:
            continue
    return ids


def _flatpak_app_ids() -> set[str]:
    if not shutil.which("flatpak"):
        return set()
    try:
        import subprocess
        out = subprocess.run(
            ["flatpak", "list", "--columns=application"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
        return {line.strip().lower() for line in out.splitlines() if line.strip()}
    except (OSError, ValueError):
        return set()


def _name_looks_installed(dirname: str, known_names: set[str]) -> bool:
    lowered = dirname.lower()
    if lowered in _IGNORE_NAMES:
        return True
    # Direct match, or substring match against any known binary/app id
    # (handles cases like "vlc" dir matching "vlc-qt" binary, etc.)
    if lowered in known_names:
        return True
    return any(lowered in name or name in lowered for name in known_names if len(name) > 3)


def scan_app_leftovers(
    should_stop: Callable[[], bool] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> ScanResult:
    result = ScanResult()
    known_names = _installed_binary_names() | _installed_desktop_app_ids() | _flatpak_app_ids()

    for root_template in _WATCHED_ROOTS:
        if should_stop and should_stop():
            break
        root = Path(os.path.expanduser(root_template))
        if not root.exists():
            continue
        try:
            entries = list(os.scandir(root))
        except OSError as exc:
            result.errors.append(f"{root}: {exc}")
            continue

        for entry in entries:
            if should_stop and should_stop():
                break
            if not entry.is_dir(follow_symlinks=False):
                continue
            result.scanned_paths += 1
            if progress_cb:
                progress_cb(entry.path)

            if _name_looks_installed(entry.name, known_names):
                continue

            size = _dir_size_safe(Path(entry.path))
            if size == 0:
                continue  # not worth surfacing empty leftovers here

            result.findings.append(
                Finding(
                    path=Path(entry.path),
                    category="app_leftover",
                    risk=RiskLevel.NEEDS_CONFIRMATION,
                    size_bytes=size,
                    reason=(
                        f"No installed application matches '{entry.name}' — "
                        "may be a leftover from a removed app. Verify before deleting."
                    ),
                    is_directory=True,
                )
            )
    return result


def _dir_size_safe(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size_safe(Path(entry.path))
            except OSError:
                continue
    except OSError:
        pass
    return total
