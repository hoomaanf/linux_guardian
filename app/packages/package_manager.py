"""Package manager abstraction.

Each distro family gets a small adapter implementing PackageManagerAdapter.
The Packages tab talks only to the adapter interface, never to raw shell
commands directly, so adding a new backend (e.g. `emerge` for Gentoo) means
adding one class here, not touching the UI.

All commands that MODIFY the system (cache clear, orphan removal) are
returned as a list[str] "plan" for the caller to review/confirm and execute
via a worker thread with pkexec/sudo — this module never executes anything
with elevated privileges itself.
"""
from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PackageInfo:
    name: str
    version: str
    size_bytes: int = 0
    explicitly_installed: bool = True


@dataclass
class CommandPlan:
    """A shell command this tool WOULD run, pending user confirmation."""
    description: str
    command: list[str]
    requires_root: bool = True


class PackageManagerAdapter(ABC):
    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def list_orphans(self) -> list[PackageInfo]:
        """Packages installed as dependencies that nothing depends on anymore."""

    @abstractmethod
    def cache_size_bytes(self) -> int:
        ...

    @abstractmethod
    def plan_clean_cache(self) -> CommandPlan:
        ...

    @abstractmethod
    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        ...

    def _run(self, args: list[str]) -> str:
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=30, check=False
            )
            return result.stdout
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return ""


class PacmanAdapter(PackageManagerAdapter):
    name = "pacman"

    def is_available(self) -> bool:
        return shutil.which("pacman") is not None

    def list_orphans(self) -> list[PackageInfo]:
        out = self._run(["pacman", "-Qdtq"])
        packages = []
        for line in out.splitlines():
            line = line.strip()
            if line:
                packages.append(PackageInfo(name=line, version="", explicitly_installed=False))
        return packages

    def cache_size_bytes(self) -> int:
        import os
        cache_dir = "/var/cache/pacman/pkg"
        total = 0
        try:
            for entry in os.scandir(cache_dir):
                if entry.is_file():
                    total += entry.stat().st_size
        except OSError:
            pass
        return total

    def plan_clean_cache(self) -> CommandPlan:
        return CommandPlan(
            description="Remove all cached package versions except the currently installed one (pacman -Sc)",
            command=["pacman", "-Sc", "--noconfirm"],
            requires_root=True,
        )

    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        names = [p.name for p in packages]
        return CommandPlan(
            description=f"Remove {len(names)} orphaned package(s) and their config files",
            command=["pacman", "-Rns", "--noconfirm", *names],
            requires_root=True,
        )


class AptAdapter(PackageManagerAdapter):
    name = "apt"

    def is_available(self) -> bool:
        return shutil.which("apt-get") is not None or shutil.which("apt") is not None

    def list_orphans(self) -> list[PackageInfo]:
        out = self._run(["apt-get", "--simulate", "autoremove"])
        packages = []
        for line in out.splitlines():
            if line.startswith("Remv "):
                parts = line.split()
                if len(parts) >= 2:
                    packages.append(PackageInfo(name=parts[1], version="", explicitly_installed=False))
        return packages

    def cache_size_bytes(self) -> int:
        import os
        cache_dir = "/var/cache/apt/archives"
        total = 0
        try:
            for entry in os.scandir(cache_dir):
                if entry.is_file():
                    total += entry.stat().st_size
        except OSError:
            pass
        return total

    def plan_clean_cache(self) -> CommandPlan:
        return CommandPlan(
            description="Remove all cached .deb files (apt-get clean)",
            command=["apt-get", "clean"],
            requires_root=True,
        )

    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        return CommandPlan(
            description="Remove packages that were automatically installed and are no longer needed",
            command=["apt-get", "autoremove", "-y"],
            requires_root=True,
        )


class DnfAdapter(PackageManagerAdapter):
    name = "dnf"

    def is_available(self) -> bool:
        return shutil.which("dnf") is not None

    def list_orphans(self) -> list[PackageInfo]:
        out = self._run(["dnf", "repoquery", "--extras", "--unneeded", "-q"])
        return [PackageInfo(name=line.strip(), version="", explicitly_installed=False)
                for line in out.splitlines() if line.strip()]

    def cache_size_bytes(self) -> int:
        import os
        total = 0
        for base in ("/var/cache/dnf", "/var/cache/yum"):
            try:
                for root, _, files in os.walk(base):
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
            except OSError:
                pass
        return total

    def plan_clean_cache(self) -> CommandPlan:
        return CommandPlan(
            description="Clear all cached dnf metadata and packages (dnf clean all)",
            command=["dnf", "clean", "all"],
            requires_root=True,
        )

    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        return CommandPlan(
            description="Remove unneeded leaf packages (dnf autoremove)",
            command=["dnf", "autoremove", "-y"],
            requires_root=True,
        )


class ZypperAdapter(PackageManagerAdapter):
    name = "zypper"

    def is_available(self) -> bool:
        return shutil.which("zypper") is not None

    def list_orphans(self) -> list[PackageInfo]:
        out = self._run(["zypper", "packages", "--orphaned"])
        packages = []
        for line in out.splitlines():
            if line.startswith("i "):
                cols = [c.strip() for c in line.split("|")]
                if len(cols) >= 3:
                    packages.append(PackageInfo(name=cols[2], version="", explicitly_installed=False))
        return packages

    def cache_size_bytes(self) -> int:
        import os
        total = 0
        try:
            for root, _, files in os.walk("/var/cache/zypp"):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def plan_clean_cache(self) -> CommandPlan:
        return CommandPlan(
            description="Clean the zypper package cache (zypper clean)",
            command=["zypper", "clean", "--all"],
            requires_root=True,
        )

    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        names = [p.name for p in packages]
        return CommandPlan(
            description=f"Remove {len(names)} orphaned package(s)",
            command=["zypper", "remove", "-y", *names],
            requires_root=True,
        )


class XbpsAdapter(PackageManagerAdapter):
    name = "xbps"

    def is_available(self) -> bool:
        return shutil.which("xbps-install") is not None

    def list_orphans(self) -> list[PackageInfo]:
        out = self._run(["xbps-query", "-O", "-m"])
        return [PackageInfo(name=line.strip(), version="", explicitly_installed=False)
                for line in out.splitlines() if line.strip()]

    def cache_size_bytes(self) -> int:
        import os
        total = 0
        try:
            for entry in os.scandir("/var/cache/xbps"):
                if entry.is_file():
                    total += entry.stat().st_size
        except OSError:
            pass
        return total

    def plan_clean_cache(self) -> CommandPlan:
        return CommandPlan(
            description="Remove obsolete cached binary packages (xbps-remove -O)",
            command=["xbps-remove", "-O", "-y"],
            requires_root=True,
        )

    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        return CommandPlan(
            description="Remove orphaned packages (xbps-remove -o)",
            command=["xbps-remove", "-o", "-y"],
            requires_root=True,
        )


class ApkAdapter(PackageManagerAdapter):
    name = "apk"

    def is_available(self) -> bool:
        return shutil.which("apk") is not None

    def list_orphans(self) -> list[PackageInfo]:
        # Alpine's apk does not track orphans the way pacman/apt do.
        return []

    def cache_size_bytes(self) -> int:
        import os
        total = 0
        try:
            for entry in os.scandir("/var/cache/apk"):
                if entry.is_file():
                    total += entry.stat().st_size
        except OSError:
            pass
        return total

    def plan_clean_cache(self) -> CommandPlan:
        return CommandPlan(
            description="Clean the apk package cache (apk cache clean)",
            command=["apk", "cache", "clean"],
            requires_root=True,
        )

    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        return CommandPlan(description="No orphan tracking available for apk", command=[], requires_root=False)


class FlatpakAdapter(PackageManagerAdapter):
    """Universal manager — coexists alongside a system adapter, never replaces it."""
    name = "flatpak"

    def is_available(self) -> bool:
        return shutil.which("flatpak") is not None

    def list_orphans(self) -> list[PackageInfo]:
        out = self._run(["flatpak", "list", "--app", "--columns=application"])
        installed = {line.strip() for line in out.splitlines() if line.strip()}
        # Unused runtimes: `flatpak uninstall --unused` handles detection itself;
        # we just report the count via a dry-run-style query.
        unused_out = self._run(["flatpak", "list", "--runtime", "--columns=application"])
        return [PackageInfo(name=n, version="", explicitly_installed=False)
                for n in unused_out.splitlines() if n.strip() and n.strip() not in installed]

    def cache_size_bytes(self) -> int:
        import os
        total = 0
        cache_dir = os.path.expanduser("~/.var/app")
        try:
            for root, _, files in os.walk(cache_dir):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def plan_clean_cache(self) -> CommandPlan:
        return CommandPlan(
            description="Remove unused Flatpak runtimes (flatpak uninstall --unused)",
            command=["flatpak", "uninstall", "--unused", "-y"],
            requires_root=False,
        )

    def plan_remove_orphans(self, packages: list[PackageInfo]) -> CommandPlan:
        return self.plan_clean_cache()


_ADAPTERS: list[type[PackageManagerAdapter]] = [
    PacmanAdapter, AptAdapter, DnfAdapter, ZypperAdapter, XbpsAdapter, ApkAdapter,
]
_UNIVERSAL_ADAPTERS: list[type[PackageManagerAdapter]] = [FlatpakAdapter]


def get_system_adapter(package_manager_name: str | None) -> PackageManagerAdapter | None:
    """Return the adapter matching the distro's detected primary PM, if any."""
    for cls in _ADAPTERS:
        adapter = cls()
        if adapter.name == package_manager_name and adapter.is_available():
            return adapter
    return None


def get_available_universal_adapters() -> list[PackageManagerAdapter]:
    return [cls() for cls in _UNIVERSAL_ADAPTERS if cls().is_available()]
