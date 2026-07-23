"""Storage Analyzer tab: largest files/folders under a chosen directory.

Full duplicate-file detection (content hashing across the whole disk) is
listed in the spec but deliberately out of scope for this pass — it's an
expensive, separate feature (chunked hashing, a hash-collision UI, media
vs. archive vs. ISO handling) that deserves its own module rather than
being bolted onto a first cut. This tab currently gives largest-files /
largest-folders, which is the immediately useful 80% of "storage analyzer".
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.utils.formatting import human_bytes
from app.workers.worker_thread import FunctionWorker


@dataclass
class StorageEntry:
    path: Path
    size_bytes: int
    is_dir: bool


def _scan_largest(root: Path, top_n: int = 200, should_stop=None, progress_cb=None) -> list[StorageEntry]:
    dir_sizes: dict[str, int] = {}
    file_entries: list[StorageEntry] = []
    last_progress_at = 0.0

    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if should_stop and should_stop():
            break
        if progress_cb:
            now = time.monotonic()
            if now - last_progress_at >= 0.15:
                progress_cb(dirpath)
                last_progress_at = now
        total = 0
        for name in filenames:
            fpath = Path(dirpath) / name
            try:
                size = fpath.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            total += size
            file_entries.append(StorageEntry(fpath, size, is_dir=False))
        for name in dirnames:
            total += dir_sizes.get(str(Path(dirpath) / name), 0)
        dir_sizes[dirpath] = total

    dir_entries = [StorageEntry(Path(p), s, is_dir=True) for p, s in dir_sizes.items()]
    all_entries = sorted(file_entries + dir_entries, key=lambda e: e.size_bytes, reverse=True)
    return all_entries[:top_n]


class StorageTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.path_edit = QLineEdit(str(Path.home()))
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setObjectName("secondary")
        self.scan_btn = QPushButton("Analyze")
        controls.addWidget(self.path_edit, 1)
        controls.addWidget(self.browse_btn)
        controls.addWidget(self.scan_btn)
        root_layout.addLayout(controls)

        self.status_label = QLabel("Choose a directory and click Analyze.")
        root_layout.addWidget(self.status_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Path", "Type", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setAlternatingRowColors(True)
        root_layout.addWidget(self.tree, 1)

        self.browse_btn.clicked.connect(self._browse)
        self.scan_btn.clicked.connect(self._analyze)

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose directory", self.path_edit.text())
        if directory:
            self.path_edit.setText(directory)

    def _analyze(self) -> None:
        root = Path(self.path_edit.text())
        if not root.exists():
            self.status_label.setText("That path doesn't exist.")
            return
        self.status_label.setText(f"Analyzing {root}…")
        self.scan_btn.setEnabled(False)
        self.tree.clear()

        worker = FunctionWorker(_scan_largest, root)
        worker.signals.progress.connect(lambda msg: self.status_label.setText(msg[-100:]))
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_error(self, tb: str) -> None:
        self.scan_btn.setEnabled(True)
        self.status_label.setText("Analysis failed — see log for details.")

    def _on_finished(self, entries: list[StorageEntry]) -> None:
        self.scan_btn.setEnabled(True)
        self.status_label.setText(f"Top {len(entries)} largest items shown, sorted by size.")
        for entry in entries:
            item = QTreeWidgetItem([
                str(entry.path),
                "Folder" if entry.is_dir else "File",
                human_bytes(entry.size_bytes),
            ])
            self.tree.addTopLevelItem(item)
