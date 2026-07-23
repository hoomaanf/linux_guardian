"""Light / Dark / Auto theming via Qt stylesheets + palettes.

Kept deliberately simple (stylesheet strings, not a full design-token
system) so it's easy to extend, but centralized here so no widget file
hardcodes a color.
"""
from __future__ import annotations

import enum

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


class ThemeMode(enum.Enum):
    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"


DEFAULT_ACCENT = "#4C8BF5"

_DARK_STYLESHEET = """
QWidget {{ background-color: #1e1f22; color: #e6e6e6; font-size: 10.5pt; }}
QMainWindow, QDialog {{ background-color: #1e1f22; }}
QTabWidget::pane {{ border: 1px solid #33353a; border-radius: 8px; }}
QTabBar::tab {{
    background: #2a2c30; padding: 8px 16px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; color: #b8b8b8;
}}
QTabBar::tab:selected {{ background: #33353a; color: white; border-bottom: 2px solid {accent}; }}
QPushButton {{
    background-color: {accent}; color: white; border: none; border-radius: 6px;
    padding: 6px 14px; font-weight: 500;
}}
QPushButton:hover {{ background-color: {accent_hover}; }}
QPushButton:disabled {{ background-color: #45474c; color: #8a8a8a; }}
QPushButton#secondary {{ background-color: #33353a; color: #e6e6e6; }}
QPushButton#secondary:hover {{ background-color: #3d3f45; }}
QPushButton#danger {{ background-color: #d64545; }}
QPushButton#danger:hover {{ background-color: #e05555; }}
QTreeWidget, QTableWidget, QListWidget {{
    background-color: #242629; border: 1px solid #33353a; border-radius: 8px;
    alternate-background-color: #2a2c30;
}}
QHeaderView::section {{
    background-color: #2a2c30; color: #b8b8b8; padding: 6px; border: none;
    border-bottom: 1px solid #33353a;
}}
QProgressBar {{
    border: none; border-radius: 6px; background-color: #2a2c30; text-align: center; height: 14px;
}}
QProgressBar::chunk {{ background-color: {accent}; border-radius: 6px; }}
QLineEdit, QComboBox {{
    background-color: #2a2c30; border: 1px solid #3d3f45; border-radius: 6px; padding: 5px 8px;
}}
QGroupBox {{
    border: 1px solid #33353a; border-radius: 8px; margin-top: 10px; padding-top: 12px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #45474c; border-radius: 5px; min-height: 24px; }}
QStatusBar {{ background-color: #2a2c30; }}
"""

_LIGHT_STYLESHEET = """
QWidget {{ background-color: #f5f6f8; color: #202124; font-size: 10.5pt; }}
QMainWindow, QDialog {{ background-color: #f5f6f8; }}
QTabWidget::pane {{ border: 1px solid #dcdde1; border-radius: 8px; }}
QTabBar::tab {{
    background: #ebecf0; padding: 8px 16px; margin-right: 2px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; color: #55565b;
}}
QTabBar::tab:selected {{ background: white; color: #202124; border-bottom: 2px solid {accent}; }}
QPushButton {{
    background-color: {accent}; color: white; border: none; border-radius: 6px;
    padding: 6px 14px; font-weight: 500;
}}
QPushButton:hover {{ background-color: {accent_hover}; }}
QPushButton:disabled {{ background-color: #d0d1d5; color: #9a9a9e; }}
QPushButton#secondary {{ background-color: #e4e5e9; color: #202124; }}
QPushButton#secondary:hover {{ background-color: #d8d9dd; }}
QPushButton#danger {{ background-color: #d64545; }}
QPushButton#danger:hover {{ background-color: #c23a3a; }}
QTreeWidget, QTableWidget, QListWidget {{
    background-color: white; border: 1px solid #dcdde1; border-radius: 8px;
    alternate-background-color: #f5f6f8;
}}
QHeaderView::section {{
    background-color: #ebecf0; color: #55565b; padding: 6px; border: none;
    border-bottom: 1px solid #dcdde1;
}}
QProgressBar {{
    border: none; border-radius: 6px; background-color: #e4e5e9; text-align: center; height: 14px;
}}
QProgressBar::chunk {{ background-color: {accent}; border-radius: 6px; }}
QLineEdit, QComboBox {{
    background-color: white; border: 1px solid #dcdde1; border-radius: 6px; padding: 5px 8px;
}}
QGroupBox {{
    border: 1px solid #dcdde1; border-radius: 8px; margin-top: 10px; padding-top: 12px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QStatusBar {{ background-color: #ebecf0; }}
"""


def _shade(hex_color: str, factor: float) -> str:
    color = QColor(hex_color)
    h, s, v, a = color.getHsv()
    v = max(0, min(255, int(v * factor)))
    color.setHsv(h, s, v, a)
    return color.name()


def apply_theme(app: QApplication, mode: ThemeMode, accent: str = DEFAULT_ACCENT) -> None:
    if mode == ThemeMode.AUTO:
        mode = _detect_system_mode()

    sheet_template = _DARK_STYLESHEET if mode == ThemeMode.DARK else _LIGHT_STYLESHEET
    stylesheet = sheet_template.format(accent=accent, accent_hover=_shade(accent, 1.15))
    app.setStyleSheet(stylesheet)


def _detect_system_mode() -> ThemeMode:
    app = QApplication.instance()
    if app is None:
        return ThemeMode.DARK
    palette = app.palette()
    bg = palette.color(QPalette.ColorRole.Window)
    brightness = (bg.red() * 299 + bg.green() * 587 + bg.blue() * 114) / 1000
    return ThemeMode.DARK if brightness < 128 else ThemeMode.LIGHT
