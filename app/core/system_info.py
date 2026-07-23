"""Point-in-time system metrics for the Dashboard tab.

Every function here is a cheap, synchronous snapshot. The UI never calls
these directly on the main thread for the polling loop — see
app/workers/worker_thread.py, which runs SystemInfoCollector.snapshot() on
a QThread and emits the result back to the dashboard widget.
"""
from __future__ import annotations

import platform
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil


@dataclass
class CpuInfo:
    percent_total: float = 0.0
    percent_per_core: list[float] = field(default_factory=list)
    freq_current_mhz: float | None = None
    freq_max_mhz: float | None = None
    temperature_c: float | None = None
    governor: str | None = None
    turbo_enabled: bool | None = None
    load_avg: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass
class MemoryInfo:
    total_bytes: int = 0
    used_bytes: int = 0
    available_bytes: int = 0
    percent: float = 0.0
    swap_total_bytes: int = 0
    swap_used_bytes: int = 0
    swap_percent: float = 0.0
    zram_active: bool = False


@dataclass
class DiskInfo:
    mountpoint: str
    device: str
    fstype: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


@dataclass
class NetworkInfo:
    bytes_sent: int = 0
    bytes_recv: int = 0
    sent_per_sec: float = 0.0
    recv_per_sec: float = 0.0


@dataclass
class SystemSnapshot:
    cpu: CpuInfo
    memory: MemoryInfo
    disks: list[DiskInfo]
    network: NetworkInfo
    boot_time_epoch: float
    kernel_version: str
    hostname: str
    timestamp: float = field(default_factory=time.time)


class SystemInfoCollector:
    """Stateful collector — keeps prior network counters to compute rates."""

    def __init__(self) -> None:
        self._prev_net = psutil.net_io_counters()
        self._prev_time = time.monotonic()

    def _read_governor(self) -> str | None:
        path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        try:
            return path.read_text().strip()
        except OSError:
            return None

    def _read_turbo(self) -> bool | None:
        # Intel: no_turbo=0 means turbo IS enabled. AMD: boost=1 means enabled.
        no_turbo = Path("/sys/devices/system/cpu/intel_pstate/no_turbo")
        amd_boost = Path("/sys/devices/system/cpu/cpufreq/boost")
        try:
            if no_turbo.exists():
                return no_turbo.read_text().strip() == "0"
            if amd_boost.exists():
                return amd_boost.read_text().strip() == "1"
        except OSError:
            pass
        return None

    def _read_cpu_temp(self) -> float | None:
        try:
            temps = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return None
        for label in ("coretemp", "k10temp", "cpu_thermal", "zenpower"):
            if label in temps and temps[label]:
                return temps[label][0].current
        for entries in temps.values():
            if entries:
                return entries[0].current
        return None

    def collect_cpu(self) -> CpuInfo:
        freq = psutil.cpu_freq()
        try:
            load_avg = psutil.getloadavg()
        except (AttributeError, OSError):
            load_avg = (0.0, 0.0, 0.0)
        return CpuInfo(
            percent_total=psutil.cpu_percent(interval=None),
            percent_per_core=psutil.cpu_percent(interval=None, percpu=True),
            freq_current_mhz=freq.current if freq else None,
            freq_max_mhz=freq.max if freq else None,
            temperature_c=self._read_cpu_temp(),
            governor=self._read_governor(),
            turbo_enabled=self._read_turbo(),
            load_avg=load_avg,
        )

    def collect_memory(self) -> MemoryInfo:
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        zram_active = any(
            Path("/sys/block").glob("zram*")
        ) if Path("/sys/block").exists() else False
        return MemoryInfo(
            total_bytes=vm.total,
            used_bytes=vm.used,
            available_bytes=vm.available,
            percent=vm.percent,
            swap_total_bytes=sm.total,
            swap_used_bytes=sm.used,
            swap_percent=sm.percent,
            zram_active=zram_active,
        )

    def collect_disks(self) -> list[DiskInfo]:
        disks = []
        for part in psutil.disk_partitions(all=False):
            if "loop" in part.device or part.fstype == "":
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append(
                DiskInfo(
                    mountpoint=part.mountpoint,
                    device=part.device,
                    fstype=part.fstype,
                    total_bytes=usage.total,
                    used_bytes=usage.used,
                    free_bytes=usage.free,
                    percent=usage.percent,
                )
            )
        return disks

    def collect_network(self) -> NetworkInfo:
        current = psutil.net_io_counters()
        now = time.monotonic()
        elapsed = max(now - self._prev_time, 1e-6)
        sent_rate = (current.bytes_sent - self._prev_net.bytes_sent) / elapsed
        recv_rate = (current.bytes_recv - self._prev_net.bytes_recv) / elapsed
        self._prev_net = current
        self._prev_time = now
        return NetworkInfo(
            bytes_sent=current.bytes_sent,
            bytes_recv=current.bytes_recv,
            sent_per_sec=max(sent_rate, 0.0),
            recv_per_sec=max(recv_rate, 0.0),
        )

    def snapshot(self) -> SystemSnapshot:
        return SystemSnapshot(
            cpu=self.collect_cpu(),
            memory=self.collect_memory(),
            disks=self.collect_disks(),
            network=self.collect_network(),
            boot_time_epoch=psutil.boot_time(),
            kernel_version=platform.release(),
            hostname=platform.node(),
        )
