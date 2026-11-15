"""Visual theme: light, Apple-like look (white surfaces, SF system font, soft rounded cards, one blue accent)."""

ACCENT = '#0071e3'
ACCENT_HOVER = '#0077ed'
ACCENT_PRESSED = '#0062c3'
TEXT = '#1d1d1f'
SECONDARY = '#6e6e73'
BORDER = '#d2d2d7'
CARD = '#f5f5f7'
GOOD = '#1d8a3a'
BAD = '#d70015'

FONT_FAMILY = '-apple-system, "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial, sans-serif'

STYLE = f"""
* {{ font-family: {FONT_FAMILY}; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#root {{ background: #ffffff; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 28px; font-weight: 700; }}
QLabel#subtitle {{ font-size: 14px; color: {SECONDARY}; }}
QLabel#stepNumber {{ background: {ACCENT}; color: white; border-radius: 12px; font-weight: 700; min-width: 24px; max-width: 24px; min-height: 24px; max-height: 24px; qproperty-alignment: AlignCenter; }}
QLabel#stepTitle {{ font-size: 17px; font-weight: 600; }}
QLabel#help {{ color: {SECONDARY}; font-size: 12px; }}
QLabel#settingName {{ font-size: 14px; font-weight: 600; }}
QFrame#card {{ background: {CARD}; border-radius: 16px; }}
QFrame#banner {{ background: #e8f2fd; border-radius: 12px; }}
QFrame#banner QLabel {{ color: #0b4a8f; font-size: 13px; }}
QFrame#separator {{ background: {BORDER}; max-height: 1px; min-height: 1px; }}

QPushButton {{ background: #ffffff; border: 1px solid {BORDER}; border-radius: 9px; padding: 6px 14px; font-size: 13px; }}
QPushButton:hover {{ background: #fafafa; }}
QPushButton:pressed {{ background: #ececef; }}
QPushButton:disabled {{ color: #a1a1a6; background: #f5f5f7; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; padding: 12px 18px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: #b9d8f8; color: white; }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT}; padding: 2px 4px; }}
QPushButton#link:hover {{ text-decoration: underline; }}

QDoubleSpinBox {{ background: #ffffff; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 8px; min-width: 90px; font-size: 14px; }}
QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QCheckBox {{ font-size: 14px; spacing: 8px; }}
QComboBox {{ background: #ffffff; border: 1px solid {BORDER}; border-radius: 8px; padding: 3px 8px; font-size: 13px; }}

QTableWidget {{ background: #ffffff; border: none; border-radius: 12px; gridline-color: transparent; font-size: 13px; alternate-background-color: #fafafa; selection-background-color: #d6e9fc; selection-color: {TEXT}; }}
QTableWidget::item {{ padding: 4px; }}
QHeaderView::section {{ background: transparent; border: none; border-bottom: 1px solid {BORDER}; padding: 6px 4px; color: {SECONDARY}; font-size: 12px; font-weight: 600; }}

QProgressBar {{ background: #e5e5ea; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QPlainTextEdit {{ background: #1d1d1f; color: #e8e8ed; border-radius: 10px; font-family: Menlo, Consolas, monospace; font-size: 12px; padding: 8px; }}
QStatusBar {{ background: #ffffff; color: {SECONDARY}; }}
QToolTip {{ background: #1d1d1f; color: white; border: none; padding: 6px; }}
"""
