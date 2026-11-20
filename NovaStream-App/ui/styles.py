"""
NovaStream Refined Professional Desktop Stylesheet
Kompakt, yüksek veri yoğunluklu, göz yormayan profesyonel koyu tema.
Gereksiz neon efektleri ve yapay zeka klişelerinden arındırılmış, verimli masaüstü deneyimi.
"""

MAIN_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #121316;
    color: #e4e6eb;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

QWidget {
    color: #e4e6eb;
    font-size: 12px;
}

/* Sol Kenar Çubuğu (Sidebar) */
#SidebarWidget {
    background-color: #16181d;
    border-right: 1px solid #23252b;
}

#SidebarTitle {
    font-size: 10px;
    font-weight: 700;
    color: #6c727d;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding: 10px 14px 4px 14px;
}

QListWidget#CategoryList {
    background-color: transparent;
    border: none;
    outline: none;
    padding: 2px 6px;
}

QListWidget#CategoryList::item {
    height: 30px;
    border-radius: 5px;
    padding-left: 8px;
    color: #9da2ad;
    font-weight: 500;
    margin: 1px 0px;
}

QListWidget#CategoryList::item:hover {
    background-color: #1f2127;
    color: #f1f3f7;
}

QListWidget#CategoryList::item:selected {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}

/* Üst Araç Çubuğu (Toolbar) */
#ToolbarWidget {
    background-color: #16181d;
    border-bottom: 1px solid #23252b;
    padding: 4px 8px;
}

QPushButton.tool-btn {
    background-color: #1f2127;
    color: #d1d5db;
    border: 1px solid #2d3038;
    border-radius: 5px;
    padding: 5px 11px;
    font-weight: 500;
    font-size: 12px;
}

QPushButton.tool-btn:hover {
    background-color: #2a2d35;
    border-color: #3b82f6;
    color: #ffffff;
}

QPushButton.tool-btn:pressed {
    background-color: #1d4ed8;
    color: #ffffff;
}

QPushButton.tool-btn-primary {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #3b82f6;
    border-radius: 5px;
    padding: 5px 14px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton.tool-btn-primary:hover {
    background-color: #1d4ed8;
    border-color: #60a5fa;
}

QPushButton.tool-btn-primary:pressed {
    background-color: #1e40af;
}

/* Ana İndirme Tablosu (Kompakt ve Yüksek Yoğunluklu) */
QTableWidget {
    background-color: #121316;
    alternate-background-color: #16181d;
    gridline-color: #202227;
    border: none;
    selection-background-color: #1e3a8a;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #16181d;
    color: #8b929e;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    border: none;
    border-bottom: 1px solid #23252b;
    border-right: 1px solid #1c1e23;
    padding: 6px 8px;
}

QTableWidget::item {
    padding: 4px 8px;
    border-bottom: 1px solid #1a1c21;
}

/* Kompakt Düz İlerleme Çubuğu */
QProgressBar {
    background-color: #1f2127;
    border: 1px solid #2d3038;
    border-radius: 3px;
    text-align: center;
    color: #ffffff;
    font-weight: 600;
    font-size: 10px;
    height: 14px;
}

QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 2px;
}

/* Durum Çubuğu */
QStatusBar {
    background-color: #16181d;
    border-top: 1px solid #23252b;
    color: #8b929e;
    font-size: 11px;
    padding: 2px 6px;
}

/* Giriş Kutuları ve Form Elemanları */
QLineEdit, QSpinBox, QComboBox {
    background-color: #1a1c21;
    border: 1px solid #2d3038;
    border-radius: 5px;
    padding: 6px 10px;
    color: #e4e6eb;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #3b82f6;
    background-color: #131417;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

/* Kaydırma Çubukları */
QScrollBar:vertical {
    border: none;
    background-color: #121316;
    width: 6px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #2d3038;
    border-radius: 3px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background-color: #3f434e;
}

QScrollBar:horizontal {
    border: none;
    background-color: #121316;
    height: 6px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: #2d3038;
    border-radius: 3px;
    min-width: 24px;
}

QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}

/* Sağ Tık Menüsü (Context Menu) */
QMenu {
    background-color: #181a1f;
    border: 1px solid #2d3038;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 20px 6px 10px;
    border-radius: 4px;
    color: #d1d5db;
    font-size: 12px;
}

QMenu::item:selected {
    background-color: #2563eb;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #262931;
    margin: 3px 6px;
}

/* İletişim ve Uyarı Pencereleri (QMessageBox, QDialog) */
QDialog, QMessageBox {
    background-color: #16181d;
    color: #e4e6eb;
}

QMessageBox QLabel {
    color: #e4e6eb;
    font-size: 12.5px;
    background: transparent;
}

QDialogButtonBox QPushButton, QMessageBox QPushButton {
    background-color: #222631;
    color: #f0f3f6;
    border: 1px solid #2e3444;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    min-width: 75px;
    min-height: 22px;
}

QDialogButtonBox QPushButton:hover, QMessageBox QPushButton:hover {
    background-color: #2b3140;
    border-color: #3f475c;
    color: #ffffff;
}

QDialogButtonBox QPushButton:pressed, QMessageBox QPushButton:pressed {
    background-color: #1a1e27;
}

QDialogButtonBox QPushButton:focus, QMessageBox QPushButton:focus {
    border-color: #3b82f6;
}
"""
