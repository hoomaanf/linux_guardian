"""Process manager tab: live process tree with kill/suspend/resume.

Listing processes touches every PID on the system each refresh, which is
cheap but not free — it runs via PollingWorker on a background thread just
like the dashboard, at a slower 2s cadence to keep CPU overhead low on
low-end machines (the spec's 2GB RAM floor).
"""
from __future__ import annotations

import signal
from dataclasses import dataclass

import psutil
from PyQt6.QtCore import QThreadPool, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.utils.formatting import human_bytes
from app.workers.worker_thread import PollingWorker


@dataclass
class ProcRow:
    pid: int
    ppid: int
    name: str
    username: str
    cpu_percent: float
    memory_bytes: int
    status: str
    nice: int


def _collect_processes() -> list[ProcRow]:
    rows = []
    for proc in psutil.process_iter(
        ["pid", "ppid", "name", "username", "cpu_percent", "memory_info", "status", "nice"]
    ):
        try:
            info = proc.info
            mem = info.get("memory_info")
            rows.append(
                ProcRow(
                    pid=info["pid"],
                    ppid=info.get("ppid") or 0,
                    name=info.get("name") or "?",
                    username=info.get("username") or "?",
                    cpu_percent=info.get("cpu_percent") or 0.0,
                    memory_bytes=mem.rss if mem else 0,
                    status=info.get("status") or "?",
                    nice=info.get("nice") or 0,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows


class ProcessTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[ProcRow] = []
        self._build_ui()
        self._start_polling()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by name or PID…")
        self.tree_view_btn = QPushButton("Tree View")
        self.tree_view_btn.setCheckable(True)
        self.tree_view_btn.setChecked(True)
        self.tree_view_btn.setObjectName("secondary")
        controls.addWidget(self.search_box, 1)
        controls.addWidget(self.tree_view_btn)
        root.addLayout(controls)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Process", "PID", "User", "CPU %", "Memory", "Status", "Nice"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self.tree, 1)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        self.search_box.textChanged.connect(self._apply_filter)
        self.tree_view_btn.toggled.connect(lambda _: self._render())

    def _start_polling(self) -> None:
        worker = PollingWorker(_collect_processes, interval_ms=2000)
        worker.signals.finished.connect(self._on_rows)
        QThreadPool.globalInstance().start(worker)
        self._worker = worker

    def stop(self) -> None:
        if hasattr(self, "_worker"):
            self._worker.request_stop()

    def _on_rows(self, rows: list[ProcRow]) -> None:
        self._rows = rows
        self.status_label.setText(f"{len(rows)} processes")
        self._render()

    def _apply_filter(self) -> None:
        self._render()

    def _render(self) -> None:
        query = self.search_box.text().strip().lower()
        rows = self._rows
        if query:
            rows = [r for r in rows if query in r.name.lower() or query == str(r.pid)]

        self.tree.clear()

        if self.tree_view_btn.isChecked():
            by_pid = {r.pid: r for r in rows}
            children: dict[int, list[ProcRow]] = {}
            for r in rows:
                children.setdefault(r.ppid, []).append(r)

            added: set[int] = set()

            def add_node(row: ProcRow, parent_item):
                if row.pid in added:
                    return
                added.add(row.pid)
                item = self._make_item(row)
                if parent_item is None:
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                for child in sorted(children.get(row.pid, []), key=lambda c: -c.cpu_percent):
                    add_node(child, item)

            roots = [r for r in rows if r.ppid not in by_pid]
            for r in sorted(roots, key=lambda x: -x.cpu_percent):
                add_node(r, None)
            # Any process whose parent was filtered out still needs to show up.
            for r in rows:
                if r.pid not in added:
                    add_node(r, None)
            self.tree.expandAll()
        else:
            for r in sorted(rows, key=lambda x: -x.cpu_percent):
                self.tree.addTopLevelItem(self._make_item(r))

    def _make_item(self, row: ProcRow) -> QTreeWidgetItem:
        item = QTreeWidgetItem([
            row.name, str(row.pid), row.username, f"{row.cpu_percent:.1f}",
            human_bytes(row.memory_bytes), row.status, str(row.nice),
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, row.pid)
        return item

    def _show_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        pid = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        kill_action = menu.addAction("Kill (SIGKILL)")
        term_action = menu.addAction("Terminate (SIGTERM)")
        suspend_action = menu.addAction("Suspend")
        resume_action = menu.addAction("Resume")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        try:
            proc = psutil.Process(pid)
            if chosen is kill_action:
                if self._confirm(f"Send SIGKILL to PID {pid} ({proc.name()})?"):
                    proc.kill()
            elif chosen is term_action:
                if self._confirm(f"Send SIGTERM to PID {pid} ({proc.name()})?"):
                    proc.terminate()
            elif chosen is suspend_action:
                proc.suspend()
            elif chosen is resume_action:
                proc.resume()
        except psutil.NoSuchProcess:
            QMessageBox.warning(self, "Process Manager", "That process no longer exists.")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Process Manager", "Permission denied — try running with elevated privileges.")

    def _confirm(self, message: str) -> bool:
        result = QMessageBox.question(
            self, "Confirm", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Yes
