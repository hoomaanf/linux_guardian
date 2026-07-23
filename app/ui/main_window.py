"""Main window: tab container + menu bar (theme switching, about)."""
from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from app.core.distro import DistroInfo
from app.ui.dashboard_tab import DashboardTab
from app.ui.packages_tab import PackagesTab
from app.ui.process_tab import ProcessTab
from app.ui.scanner_tab import ScannerTab
from app.ui.storage_tab import StorageTab
from app.ui.theme import ThemeMode, apply_theme


class MainWindow(QMainWindow):
    def __init__(self, distro: DistroInfo) -> None:
        super().__init__()
        self.distro = distro
        self.setWindowTitle("Linux Guardian")
        self.resize(1200, 800)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.dashboard_tab = DashboardTab(distro)
        self.scanner_tab = ScannerTab()
        self.process_tab = ProcessTab()
        self.storage_tab = StorageTab()
        self.packages_tab = PackagesTab(distro)

        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.scanner_tab, "Cleaner")
        self.tabs.addTab(self.process_tab, "Processes")
        self.tabs.addTab(self.storage_tab, "Storage")
        self.tabs.addTab(self.packages_tab, "Packages")

        self.statusBar().showMessage(f"{distro.pretty_name}  ·  {distro.package_manager or 'no package manager detected'}")

        self._build_menu()

    def _build_menu(self) -> None:
        menu = self.menuBar()

        view_menu = menu.addMenu("&View")
        light_action = QAction("Light Theme", self)
        dark_action = QAction("Dark Theme", self)
        auto_action = QAction("Auto (System)", self)
        for action, mode in ((light_action, ThemeMode.LIGHT), (dark_action, ThemeMode.DARK), (auto_action, ThemeMode.AUTO)):
            action.triggered.connect(lambda _, m=mode: self._set_theme(m))
            view_menu.addAction(action)

        help_menu = menu.addMenu("&Help")
        about_action = QAction("About Linux Guardian", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _set_theme(self, mode: ThemeMode) -> None:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        apply_theme(app, mode)

    def _show_about(self) -> None:
        QMessageBox.information(
            self, "About Linux Guardian",
            "Linux Guardian — cross-distribution Linux optimization & maintenance tool.\n\n"
            f"Detected: {self.distro.pretty_name}\n"
            f"Package manager: {self.distro.package_manager or 'unknown'}\n"
            f"Desktop: {self.distro.desktop_environment}",
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.dashboard_tab.stop()
        self.process_tab.stop()
        super().closeEvent(event)
