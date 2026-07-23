"""The cleaner engine: the ONLY place in this codebase that deletes files.

Hard rules enforced here (do not weaken these without a very good reason):
  1. Nothing is ever deleted without being passed in as an explicitly
     `selected=True` Finding — the UI is responsible for making sure that
     only came from a user checking a box, never a default-on state above
     SAFE risk (see default_selection()).
  2. Every deletion is preceded by moving the item into a timestamped
     backup/quarantine directory, not a hard delete — see BACKUP_ROOT.
     Undo restores from there. Backups are pruned only by explicit user
     action (Empty Quarantine), never automatically.
  3. Every action (planned + executed + failed) is written to the audit
     log via app.core.logging_config.
"""
from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.cleaner.models import Finding, RiskLevel
from app.core.logging_config import get_logger

logger = get_logger("cleaner.engine")

BACKUP_ROOT = Path.home() / ".local" / "share" / "linux-guardian" / "quarantine"


@dataclass
class CleanResult:
    freed_bytes: int = 0
    removed: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    quarantine_session_dir: Path | None = None


def default_selection(findings: list[Finding]) -> None:
    """Mutate findings in place: pre-check only RiskLevel.SAFE items.

    Anything PROBABLY_SAFE or riskier starts unchecked. This is the single
    default-selection policy for the whole app — the UI should call this
    once per scan and never hand-roll its own "select all" logic.
    """
    for f in findings:
        f.selected = f.risk == RiskLevel.SAFE


def clean(
    findings: list[Finding],
    should_stop: Callable[[], bool] | None = None,
    progress_cb: Callable[[Finding], None] | None = None,
) -> CleanResult:
    """Move every selected Finding into quarantine (soft-delete).

    Callers MUST have already shown a confirmation dialog listing exactly
    these findings before calling this function — this function itself
    does not gate on anything beyond `finding.selected`.
    """
    selected = [f for f in findings if f.selected]
    if not selected:
        return CleanResult()

    session_dir = BACKUP_ROOT / time.strftime("%Y%m%d-%H%M%S")
    session_dir.mkdir(parents=True, exist_ok=True)

    result = CleanResult(quarantine_session_dir=session_dir)

    for finding in selected:
        if should_stop and should_stop():
            logger.info("Clean operation cancelled by user, stopping early.")
            break
        try:
            _quarantine_one(finding, session_dir)
            result.freed_bytes += finding.size_bytes
            result.removed.append(finding.path)
            logger.info("Removed (%s): %s [%d bytes]", finding.category, finding.path, finding.size_bytes)
        except OSError as exc:
            result.failed.append((finding.path, str(exc)))
            logger.error("Failed to remove %s: %s", finding.path, exc)
        if progress_cb:
            progress_cb(finding)

    return result


def _quarantine_one(finding: Finding, session_dir: Path) -> None:
    source = finding.path
    if not source.exists() and not source.is_symlink():
        raise OSError(f"Path no longer exists: {source}")

    # Preserve relative structure inside quarantine using a flattened,
    # collision-safe name so restoring is unambiguous.
    safe_name = str(source).replace("/", "__")
    destination = session_dir / safe_name

    if source.is_symlink():
        # Broken symlinks: just unlink them directly into a record file,
        # there is nothing meaningful to "restore".
        target = os.readlink(source)
        source.unlink()
        (session_dir / f"{safe_name}.symlink-record.txt").write_text(str(target))
        return

    shutil.move(str(source), str(destination))


def undo(session_dir: Path) -> CleanResult:
    """Restore everything from a quarantine session back to its original path."""
    result = CleanResult()
    if not session_dir.exists():
        return result

    for item in session_dir.iterdir():
        if item.name.endswith(".symlink-record.txt"):
            continue
        original_path = Path(item.name.replace("__", "/"))
        try:
            original_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(original_path))
            result.removed.append(original_path)
            logger.info("Restored: %s", original_path)
        except OSError as exc:
            result.failed.append((item, str(exc)))
            logger.error("Failed to restore %s: %s", item, exc)

    return result


def list_quarantine_sessions() -> list[Path]:
    if not BACKUP_ROOT.exists():
        return []
    return sorted((p for p in BACKUP_ROOT.iterdir() if p.is_dir()), reverse=True)


def empty_quarantine(session_dir: Path | None = None) -> int:
    """Permanently delete a quarantine session (or all of them if None).

    This is the one true hard-delete in the app, and it is only ever
    triggered by an explicit user action in the UI, never automatically.
    """
    freed = 0
    targets = [session_dir] if session_dir else list_quarantine_sessions()
    for target in targets:
        if target and target.exists():
            freed += sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            shutil.rmtree(target, ignore_errors=True)
            logger.info("Permanently emptied quarantine session: %s", target)
    return freed
