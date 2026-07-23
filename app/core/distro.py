"""Distribution and desktop-environment detection.

Reads /etc/os-release (the standard, systemd-endorsed source of truth used
by every distro in the target list) and cross-references package managers
actually present on PATH, since a derivative distro's ID_LIKE chain is not
always a reliable guide to which package manager is installed.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


# Canonical package manager binaries we know how to drive, in priority order
# per family. Order matters: e.g. an Arch system with yay installed should
# still report pacman as the "system" manager, with yay/paru as AUR helpers.
_PM_CANDIDATES = [
    "pacman", "apt", "apt-get", "dnf", "yum", "zypper", "xbps-install", "apk", "nix-env",
]
_AUR_HELPERS = ["yay", "paru"]
_UNIVERSAL_PMS = ["flatpak", "snap", "nix"]


@dataclass
class DistroInfo:
    """Everything the rest of the app needs to know about the host distro."""

    id: str = "unknown"
    id_like: list[str] = field(default_factory=list)
    name: str = "Unknown Linux"
    version: str = ""
    pretty_name: str = "Unknown Linux"

    package_manager: str | None = None          # primary system PM, e.g. "pacman"
    aur_helper: str | None = None                # yay/paru if present (Arch family)
    universal_managers: list[str] = field(default_factory=list)  # flatpak/snap/nix present

    desktop_environment: str = "unknown"
    window_manager: str = "unknown"
    session_type: str = "unknown"                # x11 / wayland

    init_system: str = "unknown"                 # systemd / openrc / runit / sysvinit


def _parse_os_release(path: str = "/etc/os-release") -> dict[str, str]:
    data: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return data
    for line in p.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"')
    return data


def _detect_package_manager() -> str | None:
    for pm in _PM_CANDIDATES:
        if shutil.which(pm):
            return pm
    return None


def _detect_aur_helper() -> str | None:
    for helper in _AUR_HELPERS:
        if shutil.which(helper):
            return helper
    return None


def _detect_universal_managers() -> list[str]:
    return [pm for pm in _UNIVERSAL_PMS if shutil.which(pm)]


def _detect_init_system() -> str:
    if Path("/run/systemd/system").exists():
        return "systemd"
    if shutil.which("openrc"):
        return "openrc"
    if shutil.which("runit") or Path("/etc/runit").exists():
        return "runit"
    if Path("/etc/init.d").exists():
        return "sysvinit"
    return "unknown"


def _detect_desktop_environment() -> str:
    for var in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "XDG_SESSION_DESKTOP"):
        value = os.environ.get(var)
        if value:
            return value.split(":")[0]
    return "unknown"


def _detect_window_manager() -> str:
    # Best-effort: check common WM/compositor process names via /proc rather
    # than assuming Xlib is available (we may be headless / Wayland-only).
    proc = Path("/proc")
    if not proc.exists():
        return "unknown"
    known_wms = {
        "kwin_x11", "kwin_wayland", "mutter", "gnome-shell", "xfwm4",
        "openbox", "i3", "sway", "bspwm", "awesome", "hyprland", "dwm",
        "marco", "cinnamon", "budgie-wm",
    }
    try:
        for pid_dir in proc.iterdir():
            if not pid_dir.name.isdigit():
                continue
            comm_file = pid_dir / "comm"
            if comm_file.exists():
                name = comm_file.read_text(errors="ignore").strip()
                if name in known_wms:
                    return name
    except (PermissionError, FileNotFoundError):
        pass
    return "unknown"


def _detect_session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "unknown")


def detect_distro() -> DistroInfo:
    """Build a full DistroInfo snapshot for the running system."""
    osr = _parse_os_release()
    id_like_raw = osr.get("ID_LIKE", "")
    return DistroInfo(
        id=osr.get("ID", "unknown"),
        id_like=id_like_raw.split() if id_like_raw else [],
        name=osr.get("NAME", "Unknown Linux"),
        version=osr.get("VERSION_ID", ""),
        pretty_name=osr.get("PRETTY_NAME", osr.get("NAME", "Unknown Linux")),
        package_manager=_detect_package_manager(),
        aur_helper=_detect_aur_helper(),
        universal_managers=_detect_universal_managers(),
        desktop_environment=_detect_desktop_environment(),
        window_manager=_detect_window_manager(),
        session_type=_detect_session_type(),
        init_system=_detect_init_system(),
    )
