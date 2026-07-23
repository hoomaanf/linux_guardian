"""Dashboard tab: live CPU / RAM / disk / network / distro overview.

Polling happens on a background thread via PollingWorker; this widget only
ever touches Qt objects from slots connected to that worker's signals,
which Qt marshals onto the UI thread automatically through the signal/slot
queued-connection mechanism. No `time.sleep` or blocking call ever runs
here directly.
"""
from __future__ import annotations

from collections import deque

from PyQt6.QtCore import QThreadPool, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from app.core.distro import DistroInfo
from app.core.system_info import SystemInfoCollector, SystemSnapshot
from app.utils.formatting import human_bytes, human_duration, time_ago
from app.workers.worker_thread import PollingWorker


class Sparkline(QWidget):
    """Minimal dependency-free rolling line chart for a single metric."""

    def __init__(self, max_points: int = 60, color: str = "#4C8BF5", parent=None) -> None:
        super().__init__(parent)
        self._values: deque[float] = deque(maxlen=max_points)
        self._color = QColor(color)
        self.setMinimumHeight(48)

    def push(self, value: float) -> None:
        self._values.append(max(0.0, min(100.0, value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(0, 0, 0, 0))

        if len(self._values) < 2:
            painter.end()
            return

        pen = QPen(self._color)
        pen.setWidth(2)
        painter.setPen(pen)

        w, h = rect.width(), rect.height()
        n = len(self._values)
        step = w / max(n - 1, 1)
        points = []
        for i, v in enumerate(self._values):
            x = i * step
            y = h - (v / 100.0) * (h - 4) - 2
            points.append((x, y))
        for i in range(len(points) - 1):
            painter.drawLine(int(points[i][0]), int(points[i][1]), int(points[i + 1][0]), int(points[i + 1][1]))
        painter.end()


class MetricCard(QGroupBox):
    def __init__(self, title: str, color: str = "#4C8BF5", parent=None) -> None:
        super().__init__(title, parent)
        layout = QVBoxLayout(self)
        self.value_label = QLabel("—")
        self.value_label.setStyleSheet("font-size: 20pt; font-weight: 700;")
        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color: #9a9a9e;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.sparkline = Sparkline(color=color)

        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.bar)
        layout.addWidget(self.sparkline)

    def update_metric(self, percent: float, value_text: str, detail_text: str) -> None:
        self.value_label.setText(value_text)
        self.detail_label.setText(detail_text)
        self.bar.setValue(int(percent))
        self.sparkline.push(percent)


class DashboardTab(QWidget):
    def __init__(self, distro: DistroInfo, parent=None) -> None:
        super().__init__(parent)
        self.distro = distro
        self.collector = SystemInfoCollector()
        self._build_ui()
        self._start_polling()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        info_box = QGroupBox("System")
        info_layout = QGridLayout(info_box)
        self.distro_label = QLabel(self.distro.pretty_name)
        self.distro_label.setStyleSheet("font-size: 13pt; font-weight: 600;")
        info_layout.addWidget(self.distro_label, 0, 0, 1, 4)

        self.de_label = QLabel(f"Desktop: {self.distro.desktop_environment}")
        self.wm_label = QLabel(f"WM: {self.distro.window_manager}")
        self.session_label = QLabel(f"Session: {self.distro.session_type}")
        self.pm_label = QLabel(f"Package manager: {self.distro.package_manager or 'unknown'}")
        self.kernel_label = QLabel("Kernel: —")
        self.uptime_label = QLabel("Uptime: —")

        for i, w in enumerate([self.de_label, self.wm_label, self.session_label,
                                self.pm_label, self.kernel_label, self.uptime_label]):
            info_layout.addWidget(w, 1 + i // 3, i % 3)

        root.addWidget(info_box)

        grid = QGridLayout()
        self.cpu_card = MetricCard("CPU", color="#4C8BF5")
        self.mem_card = MetricCard("Memory", color="#34C759")
        self.swap_card = MetricCard("Swap", color="#FF9F0A")
        self.net_card = MetricCard("Network", color="#AF52DE")
        grid.addWidget(self.cpu_card, 0, 0)
        grid.addWidget(self.mem_card, 0, 1)
        grid.addWidget(self.swap_card, 1, 0)
        grid.addWidget(self.net_card, 1, 1)
        root.addLayout(grid)

        self.disks_box = QGroupBox("Disks")
        self.disks_layout = QVBoxLayout(self.disks_box)
        root.addWidget(self.disks_box)

        root.addStretch(1)

    def _start_polling(self) -> None:
        worker = PollingWorker(self.collector.snapshot, interval_ms=1500)
        worker.signals.finished.connect(self._on_snapshot)
        QThreadPool.globalInstance().start(worker)
        self._worker = worker  # keep a reference so it isn't stopped/garbage collected

    def stop(self) -> None:
        if hasattr(self, "_worker"):
            self._worker.request_stop()

    def _on_snapshot(self, snapshot: SystemSnapshot) -> None:
        cpu = snapshot.cpu
        self.cpu_card.update_metric(
            cpu.percent_total,
            f"{cpu.percent_total:.0f}%",
            f"{cpu.freq_current_mhz:.0f} MHz" if cpu.freq_current_mhz else "",
        )

        mem = snapshot.memory
        self.mem_card.update_metric(
            mem.percent,
            f"{mem.percent:.0f}%",
            f"{human_bytes(mem.used_bytes)} / {human_bytes(mem.total_bytes)}",
        )

        self.swap_card.update_metric(
            snapshot.memory.swap_percent,
            f"{snapshot.memory.swap_percent:.0f}%",
            f"{human_bytes(snapshot.memory.swap_used_bytes)} / {human_bytes(snapshot.memory.swap_total_bytes)}"
            + (" · ZRAM active" if snapshot.memory.zram_active else ""),
        )

        net = snapshot.network
        total_rate = net.sent_per_sec + net.recv_per_sec
        # Normalize to a rough 0-100 scale for the sparkline (10 MB/s = 100%)
        net_percent = min(100.0, (total_rate / (10 * 1024 * 1024)) * 100)
        self.net_card.update_metric(
            net_percent,
            f"↓{human_bytes(net.recv_per_sec)}/s",
            f"↑{human_bytes(net.sent_per_sec)}/s",
        )

        self.kernel_label.setText(f"Kernel: {snapshot.kernel_version}")
        self.uptime_label.setText(f"Uptime: {human_duration(__import__('time').time() - snapshot.boot_time_epoch)}")

        self._update_disks(snapshot)

    def _update_disks(self, snapshot: SystemSnapshot) -> None:
        # Rebuild disk rows only if the mountpoint set changed, to avoid
        # flicker/layout churn on every 1.5s tick.
        existing = getattr(self, "_disk_rows", {})
        current_mounts = {d.mountpoint for d in snapshot.disks}
        if set(existing.keys()) != current_mounts:
            for i in reversed(range(self.disks_layout.count())):
                self.disks_layout.itemAt(i).widget().setParent(None)
            existing = {}
            for disk in snapshot.disks:
                row = QWidget()
                row_layout = QHBoxLayout(row)
                label = QLabel(f"{disk.mountpoint} ({disk.fstype})")
                label.setMinimumWidth(220)
                bar = QProgressBar()
                bar.setRange(0, 100)
                detail = QLabel("")
                detail.setMinimumWidth(160)
                row_layout.addWidget(label)
                row_layout.addWidget(bar, 1)
                row_layout.addWidget(detail)
                self.disks_layout.addWidget(row)
                existing[disk.mountpoint] = (bar, detail)
            self._disk_rows = existing

        for disk in snapshot.disks:
            if disk.mountpoint in existing:
                bar, detail = existing[disk.mountpoint]
                bar.setValue(int(disk.percent))
                detail.setText(f"{human_bytes(disk.used_bytes)} / {human_bytes(disk.total_bytes)}")
