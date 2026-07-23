"""Deep scanner for caches, temp files, old logs, and package-manager caches.

This module only READS the filesystem and produces Finding objects — it
never deletes anything. Deletion is cleaner.cleaner_engine's job, and only
after explicit user confirmation. Keeping scan and delete in separate
modules means a bug in the scanner can never accidentally cause data loss.

Designed to run inside a QThread worker (see app/workers/worker_thread.py)
so a slow scan of a huge home directory never blocks the UI. Callers should
pass a `should_stop` callable so a running scan can be cancelled promptly.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

from app.cleaner.models import Finding, RiskLevel, ScanResult
from app.core.logging_config import get_logger

logger = get_logger("scanner.cache")

_OLD_FILE_THRESHOLD_DAYS = 30
_LARGE_FILE_THRESHOLD_BYTES = 200 * 1024 * 1024  # 200 MB

# category -> (path template relative to $HOME or absolute, risk, human reason)
# Paths starting with "~" are expanded against the user's home directory.
_CACHE_LOCATIONS: list[tuple[str, str, RiskLevel, str]] = [
    ("~/.cache", "user_cache", RiskLevel.PROBABLY_SAFE, "General application cache directory"),
    ("~/.cache/thumbnails", "thumbnail_cache", RiskLevel.SAFE, "Regenerable image/video thumbnails"),
    ("~/.local/share/Trash", "trash", RiskLevel.SAFE, "Files already sent to trash"),
    ("~/.var/app", "flatpak_data", RiskLevel.NEEDS_CONFIRMATION, "Per-app Flatpak sandboxed data — may include app data you want to keep"),
    ("/var/cache/pacman/pkg", "pacman_cache", RiskLevel.SAFE, "Cached package files, superseded versions safe to remove"),
    ("/var/cache/apt/archives", "apt_cache", RiskLevel.SAFE, "Cached .deb package files"),
    ("/var/cache/dnf", "dnf_cache", RiskLevel.SAFE, "Cached dnf metadata and packages"),
    ("/var/cache/zypp", "zypper_cache", RiskLevel.SAFE, "Cached zypper package data"),
    ("/var/cache/xbps", "xbps_cache", RiskLevel.SAFE, "Cached xbps binary packages"),
    ("/var/cache/apk", "apk_cache", RiskLevel.SAFE, "Cached apk package files"),
    ("/var/log", "system_logs", RiskLevel.NEEDS_CONFIRMATION, "System logs — old rotated logs are generally safe, active logs are not"),
    ("~/.local/share/Steam/steamapps/shadercache", "steam_shader_cache", RiskLevel.PROBABLY_SAFE, "Steam shader cache, will be regenerated on next game launch"),
    ("~/.cache/mesa_shader_cache", "mesa_shader_cache", RiskLevel.PROBABLY_SAFE, "Mesa GPU shader cache, regenerable"),
    ("/tmp", "temp_files", RiskLevel.PROBABLY_SAFE, "Temporary files, generally safe but skips files in active use"),
    ("~/.npm/_cacache", "npm_cache", RiskLevel.PROBABLY_SAFE, "npm package cache, will re-download on demand"),
    ("~/.cache/pip", "pip_cache", RiskLevel.PROBABLY_SAFE, "pip wheel/package cache"),
    ("~/.cargo/registry/cache", "cargo_cache", RiskLevel.PROBABLY_SAFE, "Rust cargo downloaded crate cache"),
    ("~/go/pkg/mod/cache", "go_cache", RiskLevel.PROBABLY_SAFE, "Go module download cache"),
]


def _expand(path_template: str) -> Path:
    if path_template.startswith("~"):
        return Path(os.path.expanduser(path_template))
    return Path(path_template)


def _dir_size(path: Path, should_stop: Callable[[], bool] | None = None) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            if should_stop and should_stop():
                return total
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path), should_stop)
            except (PermissionError, FileNotFoundError, OSError):
                continue
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return total


def scan_known_cache_locations(
    should_stop: Callable[[], bool] | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> ScanResult:
    """Check every well-known cache/temp/log location and size it up."""
    result = ScanResult()
    for path_template, category, risk, reason in _CACHE_LOCATIONS:
        if should_stop and should_stop():
            break
        path = _expand(path_template)
        # This loop only has ~18 fixed entries total (not a filesystem walk),
        # so no throttling needed here — one signal per known location.
        if progress_cb:
            progress_cb(str(path))
        if not path.exists():
            continue
        try:
            size = _dir_size(path, should_stop)
        except OSError as exc:
            result.errors.append(f"{path}: {exc}")
            continue
        result.scanned_paths += 1
        if size > 0:
            result.findings.append(
                Finding(
                    path=path,
                    category=category,
                    risk=risk,
                    size_bytes=size,
                    reason=reason,
                    is_directory=True,
                )
            )
    return result


# Hard ceiling on findings for a single old/large-file scan. Without this,
# scanning an ordinary home directory can surface tens of thousands of
# "old file" hits (almost anything untouched for 30+ days), and dumping
# all of them into a QTreeWidget synchronously on the UI thread at the end
# of the scan is what actually caused the freeze — not the background
# thread itself. We keep the first N matches and report how many were left
# out so the user isn't silently missing data.
_MAX_FINDINGS_PER_SCAN = 2000

# Minimum wall-clock gap between progress_cb calls. os.walk visits huge
# directory trees far faster than the UI can repaint a status label; emitting
# a signal per directory (sometimes thousands per second) floods the Qt
# event queue on the main thread and is the other real cause of the freeze.
_PROGRESS_THROTTLE_SECONDS = 0.15


def scan_old_and_large_files(
    root: Path,
    should_stop: Callable[[], bool] | None = None,
    progress_cb: Callable[[str], None] | None = None,
    old_days: int = _OLD_FILE_THRESHOLD_DAYS,
    large_bytes: int = _LARGE_FILE_THRESHOLD_BYTES,
    max_findings: int = _MAX_FINDINGS_PER_SCAN,
) -> ScanResult:
    """Walk `root` looking for old files and unusually large files.

    This is a user-directed scan (e.g. Downloads, home dir) rather than one
    of the fixed known-cache locations, so everything found here defaults
    to NEEDS_CONFIRMATION — the app has no way to know if a 4 GB file in
    someone's home directory is disposable or precious.
    """
    result = ScanResult()
    now = time.time()
    old_cutoff = now - (old_days * 86400)
    last_progress_at = 0.0
    truncated = 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: result.errors.append(str(e))):
        if should_stop and should_stop():
            break
        # Skip other known cache locations to avoid double-reporting.
        dirnames[:] = [d for d in dirnames if not d.startswith(".git")]

        if progress_cb:
            now_mono = time.monotonic()
            if now_mono - last_progress_at >= _PROGRESS_THROTTLE_SECONDS:
                progress_cb(dirpath)
                last_progress_at = now_mono

        for name in filenames:
            if should_stop and should_stop():
                break
            fpath = Path(dirpath) / name
            try:
                st = fpath.stat()
            except (OSError, FileNotFoundError):
                continue
            result.scanned_paths += 1

            if st.st_size >= large_bytes:
                finding = Finding(
                    path=fpath,
                    category="large_file",
                    risk=RiskLevel.NEEDS_CONFIRMATION,
                    size_bytes=st.st_size,
                    reason=f"Large file ({st.st_size / (1024**3):.2f} GB)",
                )
            elif st.st_mtime < old_cutoff:
                finding = Finding(
                    path=fpath,
                    category="old_file",
                    risk=RiskLevel.NEEDS_CONFIRMATION,
                    size_bytes=st.st_size,
                    reason=f"Not modified in over {old_days} days",
                )
            else:
                continue

            if len(result.findings) < max_findings:
                result.findings.append(finding)
            else:
                truncated += 1

    if truncated:
        result.errors.append(
            f"Stopped listing individual results after {max_findings} matches — "
            f"{truncated} more file(s) matched but were not added to the list. "
            "Narrow the folder or re-run on a subfolder to see them."
        )
    return result


def scan_broken_symlinks(
    root: Path,
    should_stop: Callable[[], bool] | None = None,
) -> ScanResult:
    result = ScanResult()
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: result.errors.append(str(e))):
        if should_stop and should_stop():
            break
        for name in filenames:
            fpath = Path(dirpath) / name
            if fpath.is_symlink() and not fpath.exists():
                result.scanned_paths += 1
                result.findings.append(
                    Finding(
                        path=fpath,
                        category="broken_symlink",
                        risk=RiskLevel.SAFE,
                        size_bytes=0,
                        reason="Symlink target no longer exists",
                    )
                )
    return result


def scan_empty_directories(
    root: Path,
    should_stop: Callable[[], bool] | None = None,
) -> ScanResult:
    result = ScanResult()
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, onerror=lambda e: result.errors.append(str(e))):
        if should_stop and should_stop():
            break
        if not dirnames and not filenames:
            result.scanned_paths += 1
            result.findings.append(
                Finding(
                    path=Path(dirpath),
                    category="empty_directory",
                    risk=RiskLevel.PROBABLY_SAFE,
                    size_bytes=0,
                    reason="Empty directory",
                    is_directory=True,
                )
            )
    return result
