"""Scanner + Cleaner tab.

Flow: Scan (background thread) -> results grouped by category, grouped by
risk, nothing above SAFE pre-checked -> user reviews/toggles -> Clean
(soft-delete to quarantine, background thread) -> summary + link to Undo.

This is the module most worth reading carefully if you're auditing the
app's safety behavior: it is the only place that turns a user click into
a call to cleaner_engine.clean().
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThreadPool, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.cleaner import cleaner_engine
from app.cleaner.models import Finding, RiskLevel, ScanResult
from app.scanner import cache_scanner, leftover_scanner
from app.utils.formatting import human_bytes
from app.workers.worker_thread import FunctionWorker

_RISK_COLORS = {
    RiskLevel.SAFE: "#34C759",
    RiskLevel.PROBABLY_SAFE: "#4C8BF5",
    RiskLevel.NEEDS_CONFIRMATION: "#FF9F0A",
    RiskLevel.DANGEROUS: "#FF3B30",
}


class ScannerTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._findings: list[Finding] = []
        self._items_by_finding: dict[int, QTreeWidgetItem] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.scan_caches_btn = QPushButton("Scan Caches && Temp Files")
        self.scan_leftovers_btn = QPushButton("Scan for App Leftovers")
        self.scan_home_btn = QPushButton("Scan Home Directory…")
        self.scan_home_btn.setObjectName("secondary")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("secondary")
        self.stop_btn.setEnabled(False)

        for btn in (self.scan_caches_btn, self.scan_leftovers_btn, self.scan_home_btn, self.stop_btn):
            controls.addWidget(btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready. Choose a scan to begin.")
        root.addWidget(self.status_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Risk", "Size", "Reason"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setAlternatingRowColors(True)
        root.addWidget(self.tree, 1)

        bottom = QHBoxLayout()
        self.select_safe_btn = QPushButton("Select Safe Only")
        self.select_safe_btn.setObjectName("secondary")
        self.select_none_btn = QPushButton("Deselect All")
        self.select_none_btn.setObjectName("secondary")
        self.total_label = QLabel("Selected: 0 B")
        self.clean_btn = QPushButton("Clean Selected")
        self.clean_btn.setObjectName("danger")
        self.clean_btn.setEnabled(False)
        self.undo_btn = QPushButton("Undo Last Clean…")
        self.undo_btn.setObjectName("secondary")

        bottom.addWidget(self.select_safe_btn)
        bottom.addWidget(self.select_none_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.total_label)
        bottom.addWidget(self.clean_btn)
        bottom.addWidget(self.undo_btn)
        root.addLayout(bottom)

        self.scan_caches_btn.clicked.connect(self._run_cache_scan)
        self.scan_leftovers_btn.clicked.connect(self._run_leftover_scan)
        self.scan_home_btn.clicked.connect(self._run_home_scan)
        self.stop_btn.clicked.connect(self._stop_scan)
        self.select_safe_btn.clicked.connect(self._select_safe_only)
        self.select_none_btn.clicked.connect(self._select_none)
        self.clean_btn.clicked.connect(self._confirm_and_clean)
        self.undo_btn.clicked.connect(self._show_undo_dialog)

    # ---- scanning ---------------------------------------------------

    def _set_scanning(self, active: bool) -> None:
        self.progress_bar.setVisible(active)
        for btn in (self.scan_caches_btn, self.scan_leftovers_btn, self.scan_home_btn):
            btn.setEnabled(not active)
        self.stop_btn.setEnabled(active)

    def _run_cache_scan(self) -> None:
        self._launch_scan(cache_scanner.scan_known_cache_locations, "Scanning known cache locations…")

    def _run_leftover_scan(self) -> None:
        self._launch_scan(leftover_scanner.scan_app_leftovers, "Scanning for leftover app data…")

    def _run_home_scan(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose directory to scan", str(Path.home()))
        if not directory:
            return
        self._launch_scan(cache_scanner.scan_old_and_large_files, f"Scanning {directory}…", root=Path(directory))

    def _launch_scan(self, fn, status_text: str, **kwargs) -> None:
        self.tree.clear()
        self._findings = []
        self._items_by_finding = {}
        self.status_label.setText(status_text)
        self._set_scanning(True)

        worker = FunctionWorker(fn, **kwargs)
        worker.signals.progress.connect(lambda msg: self.status_label.setText(msg[-100:]))
        worker.signals.finished.connect(self._on_scan_finished)
        worker.signals.error.connect(self._on_scan_error)
        self._active_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _stop_scan(self) -> None:
        if hasattr(self, "_active_worker"):
            self._active_worker.request_stop()

    def _on_scan_error(self, tb: str) -> None:
        self._set_scanning(False)
        self.status_label.setText("Scan failed.")
        QMessageBox.critical(self, "Scan Error", tb)

    def _on_scan_finished(self, result: ScanResult) -> None:
        self._set_scanning(False)
        cleaner_engine.default_selection(result.findings)
        self._findings = result.findings
        self._populate_tree(result)
        note = f" {result.errors[0]}" if result.errors else ""
        self.status_label.setText(
            f"Found {len(result.findings)} item(s), "
            f"{human_bytes(result.total_reclaimable_bytes)} reclaimable.{note}"
        )
        self._update_selected_total()

    def _populate_tree(self, result: ScanResult) -> None:
        # setUpdatesEnabled(False) stops Qt from repainting/relaying-out the
        # tree on every single addTopLevelItem/addChild call. For a scan
        # with thousands of findings, doing that per-item is what made
        # populating the results look like a freeze even though the scan
        # itself had already finished on the background thread.
        self.tree.setUpdatesEnabled(False)
        try:
            self._populate_tree_impl(result)
        finally:
            self.tree.setUpdatesEnabled(True)

    def _populate_tree_impl(self, result: ScanResult) -> None:
        self.tree.clear()
        self._items_by_finding = {}
        for category, findings in sorted(result.by_category().items()):
            category_item = QTreeWidgetItem([
                f"{category.replace('_', ' ').title()} ({len(findings)})", "", human_bytes(sum(f.size_bytes for f in findings)), ""
            ])
            category_item.setFlags(category_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            self.tree.addTopLevelItem(category_item)

            for finding in sorted(findings, key=lambda f: f.size_bytes, reverse=True):
                child = QTreeWidgetItem([
                    str(finding.path), finding.risk.label, human_bytes(finding.size_bytes), finding.reason,
                ])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked if finding.selected else Qt.CheckState.Unchecked)
                child.setForeground(1, QColor(_RISK_COLORS[finding.risk]))
                category_item.addChild(child)
                self._items_by_finding[id(finding)] = child
                child.setData(0, Qt.ItemDataRole.UserRole, finding)

        self.tree.expandAll()
        self.tree.itemChanged.connect(self._on_item_changed)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        finding = item.data(0, Qt.ItemDataRole.UserRole)
        if finding is None:
            return
        finding.selected = item.checkState(0) == Qt.CheckState.Checked
        self._update_selected_total()

    def _select_safe_only(self) -> None:
        cleaner_engine.default_selection(self._findings)
        self._refresh_checkstates()

    def _select_none(self) -> None:
        for f in self._findings:
            f.selected = False
        self._refresh_checkstates()

    def _refresh_checkstates(self) -> None:
        for f in self._findings:
            item = self._items_by_finding.get(id(f))
            if item:
                item.setCheckState(0, Qt.CheckState.Checked if f.selected else Qt.CheckState.Unchecked)
        self._update_selected_total()

    def _update_selected_total(self) -> None:
        total = sum(f.size_bytes for f in self._findings if f.selected)
        count = sum(1 for f in self._findings if f.selected)
        self.total_label.setText(f"Selected: {count} item(s), {human_bytes(total)}")
        self.clean_btn.setEnabled(count > 0)

    # ---- cleaning -----------------------------------------------------

    def _confirm_and_clean(self) -> None:
        selected = [f for f in self._findings if f.selected]
        if not selected:
            return

        risky = [f for f in selected if f.risk >= RiskLevel.NEEDS_CONFIRMATION]
        message = (
            f"About to move {len(selected)} item(s) totaling "
            f"{human_bytes(sum(f.size_bytes for f in selected))} into quarantine.\n\n"
            "Nothing is permanently deleted — this can be undone from "
            "'Undo Last Clean…' until you empty the quarantine.\n"
        )
        if risky:
            message += f"\n⚠ {len(risky)} item(s) are flagged 'Needs Confirmation' or 'Dangerous'. Review them carefully."

        confirm = QMessageBox.question(
            self, "Confirm Clean", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.status_label.setText("Cleaning…")
        self.clean_btn.setEnabled(False)
        worker = FunctionWorker(cleaner_engine.clean, selected)
        worker.signals.finished.connect(self._on_clean_finished)
        worker.signals.error.connect(self._on_scan_error)
        QThreadPool.globalInstance().start(worker)

    def _on_clean_finished(self, result: cleaner_engine.CleanResult) -> None:
        self.status_label.setText(
            f"Freed {human_bytes(result.freed_bytes)} across {len(result.removed)} item(s)."
            + (f" {len(result.failed)} failed." if result.failed else "")
        )
        removed_paths = set(result.removed)
        self._findings = [f for f in self._findings if f.path not in removed_paths]
        # Rebuild the tree from the remaining findings so cleaned items disappear.
        remaining = ScanResult(findings=self._findings)
        self._populate_tree(remaining)
        self._update_selected_total()

        if result.quarantine_session_dir:
            QMessageBox.information(
                self, "Clean Complete",
                f"Items moved to quarantine:\n{result.quarantine_session_dir}\n\n"
                "Use 'Undo Last Clean…' to restore them if needed.",
            )

    def _show_undo_dialog(self) -> None:
        sessions = cleaner_engine.list_quarantine_sessions()
        if not sessions:
            QMessageBox.information(self, "Undo", "No quarantine sessions found.")
            return
        latest = sessions[0]
        confirm = QMessageBox.question(
            self, "Undo Last Clean",
            f"Restore all items from the most recent clean session?\n\n{latest}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        result = cleaner_engine.undo(latest)
        QMessageBox.information(
            self, "Undo Complete",
            f"Restored {len(result.removed)} item(s)."
            + (f" {len(result.failed)} failed." if result.failed else ""),
        )
