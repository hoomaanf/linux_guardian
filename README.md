# Linux Guardian

A cross-distribution Linux system optimization and maintenance tool, built with Python 3.13+ and PyQt6.

Auto-detects your distro, package manager, and desktop environment, and gives you a live dashboard,
a safety-first cache/leftover cleaner, a process manager, a storage analyzer, and package cache/orphan
management — all off the UI thread, nothing deleted without your confirmation.

## Status: working core, not the full original wishlist

This repository is a genuine, functioning first implementation, not a stub or mockup. It runs, it has
tests, and its cleaner logic (the most safety-sensitive part) is unit-tested to prove that unselected
items are never touched and that deletion is always a reversible move-to-quarantine, never a hard delete.

It deliberately does **not** yet implement every feature from the original wish list — SMART/NVMe
diagnostics, vendor-specific battery tools (ThinkPad/Dell/ASUS/Framework), a plugin API, PDF/HTML/CSV
report export, a duplicate-file/media hash-comparison engine, a visual treemap, kernel-parameter tuning,
and boot-time analysis are all real, substantial features that were intentionally left out of this pass
rather than faked with placeholder code. See **Roadmap** below.

## What's implemented

| Area | What it does |
|---|---|
| **Distro detection** (`app/core/distro.py`) | Parses `/etc/os-release`, detects package manager, AUR helper, DE, WM, session type, init system |
| **Dashboard** (`app/ui/dashboard_tab.py`) | Live CPU (total + freq), RAM, swap, ZRAM detection, per-disk usage, network throughput — polls in the background, never blocks the UI |
| **Deep Scanner** (`app/scanner/`) | Known cache/temp/log locations across all target distros' package managers, dev-tool caches (npm/pip/cargo/go), old/large file scan, broken symlinks, empty dirs |
| **Leftover Detection** (`app/scanner/leftover_scanner.py`) | Flags `~/.config`, `~/.cache`, `~/.local/share`, `~/.var/app` dirs that don't match any installed binary/desktop entry/Flatpak app |
| **Cleaner Engine** (`app/cleaner/cleaner_engine.py`) | Risk-leveled (Safe/Probably Safe/Needs Confirmation/Dangerous), soft-delete to a timestamped quarantine dir, full Undo, audit log |
| **Packages** (`app/packages/package_manager.py`) | Adapters for pacman, apt, dnf, zypper, xbps, apk, flatpak — cache size, orphan detection, confirm-before-run command plans |
| **Process Manager** (`app/ui/process_tab.py`) | Live tree view, CPU/mem/status/nice, kill/terminate/suspend/resume, search filter |
| **Storage Analyzer** (`app/ui/storage_tab.py`) | Largest files/folders under any chosen directory |
| **Theming** (`app/ui/theme.py`) | Light / Dark / Auto (follows system palette), accent color support |

## What's intentionally not built yet (Roadmap)

- SSD/NVMe SMART health, wear level, TRIM status
- Battery health + vendor-specific features (ThinkPad/Dell/ASUS/HP/Framework)
- Kernel parameter tuning, IO scheduler, NUMA, Huge Pages controls
- Boot time analysis / systemd-analyze integration, startup manager, service analyzer
- Duplicate file/media/ISO detection via content hashing
- Interactive treemap visualization
- Plugin system
- HTML/PDF/CSV/Markdown report export
- Localization (i18n)
- Snap/Nix package manager adapters (Flatpak is implemented; these follow the same pattern)

Each of these is a real, separable feature — adding them means writing one new adapter/module and
wiring one new tab, following the same pattern as the existing modules.

## Architecture

```
app/
  core/       distro & system detection, logging
  scanner/    read-only filesystem scanners (never delete anything)
  cleaner/    risk model + the ONLY module allowed to delete/quarantine files
  packages/   package manager adapters (pacman/apt/dnf/zypper/xbps/apk/flatpak)
  workers/    QThreadPool-based worker wrappers — every long-running call goes through here
  ui/         PyQt6 tabs + theming
  utils/      formatting helpers
tests/        unit tests (cleaner safety behavior, distro parsing)
```

Key design decisions:
- **Scan and delete are separate modules.** `app/scanner/` only reads and reports `Finding` objects;
  `app/cleaner/cleaner_engine.py` is the only code path that touches the filesystem destructively, and
  even then it moves files to `~/.local/share/linux-guardian/quarantine/<timestamp>/` rather than
  deleting them, so every clean action is reversible via Undo until the user explicitly empties
  quarantine.
- **Nothing above `RiskLevel.SAFE` is pre-selected.** `cleaner_engine.default_selection()` is the single
  place this policy lives — the UI must not hand-roll its own "select all" behavior.
- **Every long operation runs off the UI thread** via `app/workers/worker_thread.py`'s `FunctionWorker`
  / `PollingWorker`, which auto-detects `should_stop`/`progress_cb` parameters so scanners get
  cancellation and live progress for free.
- **Package-manager-mutating actions are never auto-run.** `package_manager.py` adapters return a
  `CommandPlan` (description + command list) that the UI must show to the user and get explicit
  confirmation for before executing via `pkexec`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

## Packaging (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --name linux-guardian --onefile --windowed main.py
```

(Note: PyQt6 apps built with PyInstaller often need `--hidden-import` flags for platform plugins on
some distros — if the built binary fails to find a Qt platform plugin, add
`--collect-all PyQt6`.)

## Safety model

- Nothing is ever deleted without an explicit, user-checked selection.
- Deletion is always a move into a timestamped quarantine directory, never a hard delete.
- Every scan/clean/package action is written to `~/.local/share/linux-guardian/logs/linux-guardian.log`.
- Package-manager and orphan-removal actions always show the exact shell command before running it.
- `cleaner_engine.empty_quarantine()` — the one true permanent-delete function in the codebase — is only
  ever called from an explicit "Empty Quarantine" user action, never automatically.
