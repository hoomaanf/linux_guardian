#!/usr/bin/env python3
"""Linux Guardian entry point.

Run with:  python3 main.py
"""

from __future__ import annotations

import os
import sys
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.core.distro import detect_distro
from app.core.logging_config import setup_logging
from app.ui.main_window import MainWindow
from app.ui.theme import ThemeMode, apply_theme


def main() -> int:
    logger = setup_logging()
    logger.info("Starting Linux Guardian")

    if not sys.platform.startswith("linux"):
        print("Linux Guardian only supports Linux.", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(current_dir, "app", "icon", "logo.png")

    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        logger.info(f"Icon loaded from: {icon_path}")
    else:
        logger.warning(f"Icon not found at: {icon_path}")

    app.setApplicationName("Linux Guardian")
    app.setOrganizationName("LinuxGuardian")

    distro = detect_distro()
    logger.info(
        "Detected distro: %s (package manager: %s)",
        distro.pretty_name,
        distro.package_manager,
    )

    if distro.package_manager is None:
        QMessageBox.warning(
            None,
            "No Package Manager Detected",
            "Linux Guardian could not detect a supported package manager "
            "(pacman, apt, dnf, zypper, xbps, apk). Package-related "
            "features will be disabled, but system scanning and cleaning "
            "will still work.",
        )

    apply_theme(app, ThemeMode.AUTO)

    window = MainWindow(distro)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
