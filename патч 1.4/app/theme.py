"""Shared UI tokens. Brand sources and contrast results: docs/VISUAL_STYLE.md."""
import json
from pathlib import Path
from string import Template
from PySide6.QtGui import QColor, QPalette

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
COLORS = json.loads((ASSETS / 'theme.json').read_text(encoding='utf-8'))


def apply_theme(app):
    palette = QPalette()
    roles = {'Window': 'background', 'WindowText': 'text', 'Base': 'surface',
             'AlternateBase': 'surface_alt', 'Text': 'text', 'Button': 'surface',
             'ButtonText': 'text', 'Highlight': 'primary', 'HighlightedText': 'surface',
             'ToolTipBase': 'sidebar', 'ToolTipText': 'surface', 'PlaceholderText': 'muted'}
    for role, token in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(COLORS[token]))
    for role in ('Text', 'ButtonText', 'WindowText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor(COLORS['disabled']))
    app.setPalette(palette)
    app.setStyleSheet(Template((ASSETS / 'styles.qss').read_text(encoding='utf-8')).substitute(COLORS, check_icon=(ASSETS/'icons/check-white.svg').as_posix()))
