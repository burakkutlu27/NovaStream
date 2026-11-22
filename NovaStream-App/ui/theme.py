"""
NovaStream tema sistemi: tek kaynaktan açık/koyu tema.

- Renkler TOKENS'ta tanımlıdır; ekranlar renk yazmaz, token adı kullanır.
- "system" modunda Windows/Linux'un açık-koyu ayarı izlenir ve değişince anında uygulanır.
- İkon SVG'leri tek renklidir; temaya göre yeniden renklendirilip önbelleğe yazılır.
"""

import os
import re
import tempfile

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap

ICON_SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icons")
_CACHE_DIR = os.path.join(tempfile.gettempdir(), "novastream-icons")

TOKENS = {
    "dark": {
        "bg": "#18181a", "surface": "#1f1f22", "raised": "#28282c",
        "border": "#2f2f34", "border_strong": "#5a5a62",
        # Kutucuk gibi kontrollerin çerçevesi: WCAG 1.4.11 için zemine karşı en az 3:1
        "control": "#7a7a82",
        "text": "#ececef", "text2": "#a9a9b0", "text3": "#86868e",
        "accent": "#2fb3a6", "accent_hover": "#45c4b7", "on_accent": "#0b1f1d",
        "accent_soft": "rgba(47,179,166,0.16)",
        "warn": "#d9a13b", "danger": "#e5645e", "danger_soft": "rgba(229,100,94,0.12)",
        "track": "#2c2c31",
    },
    "light": {
        "bg": "#f4f4f2", "surface": "#ffffff", "raised": "#ebebe8",
        "border": "#e0e0dc", "border_strong": "#b9b9b4",
        "control": "#8a8a90",
        "text": "#1c1c1e", "text2": "#55555b", "text3": "#6e6e74",
        "accent": "#0e7f76", "accent_hover": "#0b6d65", "on_accent": "#ffffff",
        "accent_soft": "rgba(14,127,118,0.12)",
        "warn": "#9a6200", "danger": "#c2362f", "danger_soft": "rgba(194,54,47,0.08)",
        "track": "#e4e4e0",
    },
}

# Durum -> renk token'ı (tabloda nokta, ilerleme çubuğu ve ilerleme penceresi aynı eşlemeyi kullanır)
STATUS_TOKEN = {
    "downloading": "accent",
    "paused": "warn",
    "error": "danger",
    "completed": "text3",
    "queued": "text3",
}

QSS = """
QWidget {{ color: {text}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {bg}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px 8px; }}

/* Metin rolleri */
QLabel[role="title"] {{ font-size: 16px; font-weight: 600; }}
QLabel[role="hero"] {{ font-size: 26px; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 13px; font-weight: 600; padding-top: 6px; }}
QLabel[role="muted"] {{ color: {text2}; }}
QLabel[role="caption"] {{ color: {text3}; font-size: 12px; }}
QLabel[role="danger"] {{ color: {danger}; }}
QFrame[role="separator"] {{ background: {border}; max-height: 1px; min-height: 1px; border: none; }}
QFrame[role="error-box"] {{ background: {danger_soft}; border: 1px solid {danger}; border-radius: 8px; }}
QWidget[role="bar"] {{ background: {surface}; }}

/* Butonlar: varsayılan ikincil, .tool-btn sade, .tool-btn-primary tek vurgu */
QPushButton {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 6px;
    padding: 6px 14px; }}
QPushButton:hover {{ background: {raised}; }}
QPushButton:focus {{ border-color: {accent}; }}
QPushButton:disabled {{ color: {text3}; background: transparent; border-color: {border}; }}
QPushButton.tool-btn {{ background: transparent; border: 1px solid transparent; color: {text2}; padding: 6px 10px; }}
QPushButton.tool-btn:hover {{ background: {raised}; color: {text}; }}
QPushButton.tool-btn:focus {{ border-color: {accent}; }}
QPushButton.tool-btn:disabled {{ color: {text3}; background: transparent; border-color: transparent; }}
QPushButton.tool-btn-primary {{ background: {accent}; color: {on_accent}; border: 1px solid {accent};
    padding: 7px 16px; font-weight: 600; }}
QPushButton.tool-btn-primary:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton.tool-btn-primary:focus {{ border-color: {text}; }}
QPushButton[role="danger"] {{ background: {danger}; color: #ffffff; border-color: {danger}; font-weight: 600; }}

/* Form */
QLineEdit, QSpinBox, QComboBox, QTextEdit {{ background: {surface}; border: 1px solid {border};
    border-radius: 6px; padding: 6px 10px; selection-background-color: {accent}; selection-color: {on_accent}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{ border-color: {accent}; }}
QTextEdit {{ color: {text2}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({chevron_down}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; outline: none;
    selection-background-color: {accent_soft}; selection-color: {text}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 20px; background: transparent; }}
QSpinBox::up-arrow {{ image: url({chevron_up}); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url({chevron_down}); width: 12px; height: 12px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTableView::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator:unchecked, QTableView::indicator:unchecked {{ image: url({checkbox_off}); }}
QCheckBox::indicator:checked, QTableView::indicator:checked {{ image: url({checkbox_on}); }}
QCheckBox:focus {{ color: {accent}; }}

/* Ana pencere */
#ToolbarWidget {{ background: {bg}; border-bottom: 1px solid {border}; }}
#SidebarWidget {{ background: {surface}; border-right: 1px solid {border}; }}
#SidebarTitle {{ color: {text3}; font-size: 12px; font-weight: 600; padding: 14px 16px 6px 16px; }}
QListWidget#CategoryList {{ background: transparent; border: none; outline: none; padding: 0 8px; }}
QListWidget#CategoryList::item {{ height: 32px; padding-left: 8px; border-radius: 6px; color: {text2}; }}
QListWidget#CategoryList::item:hover {{ background: {raised}; color: {text}; }}
QListWidget#CategoryList::item:selected {{ background: {accent_soft}; color: {text}; font-weight: 600; }}

QTableWidget {{ background: {bg}; border: none; gridline-color: transparent; outline: none;
    selection-background-color: {accent_soft}; selection-color: {text}; }}
QTableWidget::item {{ padding: 0 8px; border-bottom: 1px solid {border}; }}
QHeaderView::section {{ background: {bg}; color: {text3}; font-size: 12px; font-weight: 600;
    border: none; border-bottom: 1px solid {border}; padding: 8px 8px; }}

/* İlerleme: ince çubuk, renk duruma göre */
QProgressBar {{ background: {track}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar[size="large"] {{ border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
QProgressBar[state="paused"]::chunk {{ background: {warn}; }}
QProgressBar[state="error"]::chunk {{ background: {danger}; }}
QProgressBar[state="completed"]::chunk, QProgressBar[state="queued"]::chunk {{ background: {text3}; }}

QStatusBar {{ background: {bg}; border-top: 1px solid {border}; color: {text2}; font-size: 12px; }}
QStatusBar QLabel {{ color: {text2}; padding: 0 8px; }}
QStatusBar QLabel[role="danger"] {{ color: {danger}; }}
QStatusBar::item {{ border: none; }}

QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 20px 6px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent_soft}; }}
QMenu::item:disabled {{ color: {text3}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 6px; }}
QMessageBox QLabel {{ background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border_strong}; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border_strong}; border-radius: 4px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    width: 0; height: 0; background: transparent; }}
"""


class _Notifier(QObject):
    changed = pyqtSignal()


_state = {"mode": "system", "name": "dark", "app": None, "hooked": False}
_notifier = None
_icon_cache = {}


def notifier():
    """Tema değişince yayınlanan sinyal (ikonları yeniden çizmesi gereken pencereler bağlanır)."""
    global _notifier
    if _notifier is None:
        _notifier = _Notifier()
    return _notifier


def name():
    return _state["name"]


def tokens():
    return TOKENS[_state["name"]]


def color(key):
    return QColor(tokens()[key])


def _system_scheme(app):
    try:
        scheme = app.styleHints().colorScheme()
    except AttributeError:  # Qt < 6.5
        return "dark"
    if scheme == Qt.ColorScheme.Light:
        return "light"
    # Bilinmiyorsa (bazı Linux masaüstleri) uygulamanın önceki görünümü olan koyu
    return "dark"


def _resolve(mode, app):
    if mode in ("dark", "light"):
        return mode
    return _system_scheme(app)


def _recolor_svg(svg, t, role):
    if role == "checkbox":
        return (svg.replace("#1a1c21", t["surface"]).replace("#4b5160", t["control"])
                .replace("#2563eb", t["accent"]).replace('stroke="#ffffff"', f'stroke="{t["on_accent"]}"'))
    return re.sub(r'stroke="#[0-9a-fA-F]{6}"', f'stroke="{t[role]}"', svg)


def icon_path(file_name, role="text2"):
    """Temaya göre renklendirilmiş SVG'nin dosya yolu (stil sayfası url() için de kullanılır)."""
    if file_name.startswith("checkbox-"):
        role = "checkbox"
    key = (_state["name"], file_name, role)
    path = _icon_cache.get(key)
    if path and os.path.exists(path):
        return path
    src = os.path.join(ICON_SRC_DIR, file_name)
    if not os.path.exists(src):
        return src
    with open(src, encoding="utf-8") as f:
        svg = _recolor_svg(f.read(), tokens(), role)
    os.makedirs(_CACHE_DIR, exist_ok=True)
    path = os.path.join(_CACHE_DIR, f"{_state['name']}-{role}-{file_name}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    _icon_cache[key] = path
    return path


def icon(file_name, role="text2"):
    path = icon_path(file_name, role)
    return QIcon(path) if os.path.exists(path) else QIcon()


def _url(file_name):
    # Qt stil sayfası url() içinde ters eğik çizgiyi kabul etmez
    return icon_path(file_name).replace("\\", "/")


def status_dot(status):
    """Durum sütunundaki küçük renkli nokta."""
    key = (_state["name"], "dot", status)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(10, 10)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color(STATUS_TOKEN.get(status, "text3")))
    p.drawEllipse(1, 1, 8, 8)
    p.end()
    ic = QIcon(pm)
    _icon_cache[key] = ic
    return ic


def stylesheet():
    t = dict(tokens())
    t.update(
        chevron_down=_url("chevron-down.svg"),
        chevron_up=_url("chevron-up.svg"),
        checkbox_off=_url("checkbox-off.svg"),
        checkbox_on=_url("checkbox-on.svg"),
    )
    return QSS.format(**t)


def _palette():
    t = tokens()
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: "bg", QPalette.ColorRole.Base: "bg",
        QPalette.ColorRole.AlternateBase: "surface", QPalette.ColorRole.Button: "surface",
        QPalette.ColorRole.Text: "text", QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.ButtonText: "text", QPalette.ColorRole.ToolTipBase: "surface",
        QPalette.ColorRole.ToolTipText: "text", QPalette.ColorRole.PlaceholderText: "text3",
        QPalette.ColorRole.Highlight: "accent", QPalette.ColorRole.HighlightedText: "on_accent",
        QPalette.ColorRole.Mid: "border", QPalette.ColorRole.Link: "accent",
    }
    for role, key in roles.items():
        pal.setColor(role, QColor(t[key]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t["text3"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t["text3"]))
    return pal


def _font():
    families = set(QFontDatabase.families())
    for fam in ("Segoe UI Variable Text", "Segoe UI"):
        if fam in families:
            return QFont(fam)
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)


def apply(app, mode=None):
    """Temayı uygulamaya uygular. mode: "system" (varsayılan), "dark" veya "light"."""
    if mode is not None:
        _state["mode"] = mode if mode in ("system", "dark", "light") else "system"
    _state["app"] = app
    _state["name"] = _resolve(_state["mode"], app)
    _icon_cache.clear()
    app.setStyle("Fusion")  # tüm platformlarda aynı çizim; renkler palet ve stil sayfasından
    app.setFont(_font())
    app.setPalette(_palette())
    app.setStyleSheet(stylesheet())
    if not _state["hooked"]:
        try:
            app.styleHints().colorSchemeChanged.connect(lambda *_: _on_system_change())
            _state["hooked"] = True
        except AttributeError:
            pass
    notifier().changed.emit()


def _on_system_change():
    app = _state["app"]
    if app is not None and _state["mode"] == "system" and _resolve("system", app) != _state["name"]:
        apply(app)


def repolish(widget):
    """Dinamik özellik (ör. state) değişince stil sayfasının yeniden uygulanması için."""
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()
