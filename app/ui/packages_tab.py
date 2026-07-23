"""Packages tab: cache size, orphan packages, per-manager cleanup actions.

Anything that mutates the system (cache clear, orphan removal) goes
through a CommandPlan the user must explicitly confirm; this tab never
shells out to a privileged command on its own initiative.
"""
from __future__ import annotations

import subprocess

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app.core.distro import DistroInfo
from app.packages.package_manager import (
    CommandPlan, PackageInfo, get_available_universal_adapters, get_system_adapter,
)
from app.utils.formatting import human_bytes
from app.workers.worker_thread import FunctionWorker


def _run_plan(plan: CommandPlan) -> tuple[bool, str]:
    if not plan.command:
        return True, "Nothing to do."
    cmd = (["pkexec", *plan.command] if plan.requires_root else plan.command)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        ok = result.returncode == 0
        return ok, (result.stdout + result.stderr)[-4000:]
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        return False, str(exc)


class PackagesTab(QWidget):
    def __init__(self, distro: DistroInfo, parent=None) -> None:
        super().__init__(parent)
        self.distro = distro
        self.system_adapter = get_system_adapter(distro.package_manager)
        self.universal_adapters = get_available_universal_adapters()
        self._orphans: list[PackageInfo] = []
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        header = QLabel(
            f"System package manager: {self.system_adapter.name if self.system_adapter else 'not detected'}"
            + (f"  ·  AUR helper: {self.distro.aur_helper}" if self.distro.aur_helper else "")
        )
        header.setStyleSheet("font-weight: 600;")
        root.addWidget(header)

        cache_box = QGroupBox("Package Cache")
        cache_layout = QHBoxLayout(cache_box)
        self.cache_size_label = QLabel("Calculating…")
        self.clean_cache_btn = QPushButton("Clean Cache")
        cache_layout.addWidget(self.cache_size_label, 1)
        cache_layout.addWidget(self.clean_cache_btn)
        root.addWidget(cache_box)

        orphan_box = QGroupBox("Orphaned Packages")
        orphan_layout = QVBoxLayout(orphan_box)
        self.orphan_list = QListWidget()
        orphan_layout.addWidget(self.orphan_list)
        orphan_btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setObjectName("secondary")
        self.remove_orphans_btn = QPushButton("Remove Selected Orphans")
        self.remove_orphans_btn.setObjectName("danger")
        orphan_btn_row.addWidget(self.refresh_btn)
        orphan_btn_row.addStretch(1)
        orphan_btn_row.addWidget(self.remove_orphans_btn)
        orphan_layout.addLayout(orphan_btn_row)
        root.addWidget(orphan_box, 1)

        if self.universal_adapters:
            uni_box = QGroupBox("Universal Package Managers")
            uni_layout = QVBoxLayout(uni_box)
            for adapter in self.universal_adapters:
                row = QHBoxLayout()
                row.addWidget(QLabel(adapter.name))
                clean_btn = QPushButton(f"Clean unused {adapter.name} data")
                clean_btn.clicked.connect(lambda _, a=adapter: self._clean_cache(a))
                row.addWidget(clean_btn)
                uni_layout.addLayout(row)
            root.addWidget(uni_box)

        self.clean_cache_btn.clicked.connect(lambda: self._clean_cache(self.system_adapter))
        self.refresh_btn.clicked.connect(self._refresh)
        self.remove_orphans_btn.clicked.connect(self._remove_selected_orphans)

        if not self.system_adapter:
            self.clean_cache_btn.setEnabled(False)
            self.remove_orphans_btn.setEnabled(False)
            self.cache_size_label.setText("No supported package manager detected on this system.")

    def _refresh(self) -> None:
        if not self.system_adapter:
            return
        self.cache_size_label.setText("Calculating…")
        self.orphan_list.clear()

        size_worker = FunctionWorker(self.system_adapter.cache_size_bytes)
        size_worker.signals.finished.connect(
            lambda size: self.cache_size_label.setText(f"Cache size: {human_bytes(size)}")
        )
        QThreadPool.globalInstance().start(size_worker)

        orphan_worker = FunctionWorker(self.system_adapter.list_orphans)
        orphan_worker.signals.finished.connect(self._on_orphans)
        QThreadPool.globalInstance().start(orphan_worker)

    def _on_orphans(self, orphans: list[PackageInfo]) -> None:
        self._orphans = orphans
        self.orphan_list.clear()
        for pkg in orphans:
            item = QListWidgetItem(pkg.name)
            item.setSelected(False)
            self.orphan_list.addItem(item)
        self.remove_orphans_btn.setEnabled(bool(orphans))

    def _clean_cache(self, adapter) -> None:
        if not adapter:
            return
        plan = adapter.plan_clean_cache()
        self._confirm_and_run(plan, on_success=self._refresh)

    def _remove_selected_orphans(self) -> None:
        if not self.system_adapter:
            return
        selected_names = {item.text() for item in self.orphan_list.selectedItems()}
        targets = [p for p in self._orphans if p.name in selected_names] or self._orphans
        plan = self.system_adapter.plan_remove_orphans(targets)
        self._confirm_and_run(plan, on_success=self._refresh)

    def _confirm_and_run(self, plan: CommandPlan, on_success) -> None:
        if not plan.command:
            QMessageBox.information(self, "Nothing to do", plan.description)
            return
        confirm = QMessageBox.question(
            self, "Confirm Action",
            f"{plan.description}\n\nCommand: {' '.join(plan.command)}"
            + ("\n\nThis requires administrator privileges (pkexec)." if plan.requires_root else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        worker = FunctionWorker(_run_plan, plan)
        worker.signals.finished.connect(lambda res: self._on_command_done(res, on_success))
        QThreadPool.globalInstance().start(worker)

    def _on_command_done(self, result: tuple[bool, str], on_success) -> None:
        ok, output = result
        if ok:
            QMessageBox.information(self, "Done", "Action completed successfully.")
            on_success()
        else:
            QMessageBox.warning(self, "Action Failed", output or "Unknown error.")
