"""
Theme Switcher Plugin for Scrapy Spider Manager.
Adds a menu item to switch between light, dark, and extra themes.
"""
import logging
from PySide6 import QtWidgets
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QRadioButton, QButtonGroup, QVBoxLayout, QWidget, QLabel
from app.plugin_base import PluginBase
logger = logging.getLogger(__name__)

# Define styles for light, dark, and additional themes
LIGHT_THEME = """
/* Light theme */
QWidget {
    background-color: #ffffff;
    color: #000000;
}
QMenuBar, QMenu, QToolBar {
    background-color: #f0f0f0;
}
QTableWidget, QTreeView, QListWidget, QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    color: #333333;
}
"""

DARK_THEME = """
/* Dark theme */
QWidget {
    background-color: #2b2b2b;
    color: #dddddd;
}
QMenuBar, QMenu, QToolBar {
    background-color: #333333;
}
QTableWidget, QTreeView, QListWidget, QTextEdit, QPlainTextEdit {
    background-color: #363636;
    color: #dddddd;
}
"""

SOLARIZED_DARK_THEME = """
/* Solarized Dark theme */
QWidget {
    background-color: #002b36;
    color: #93a1a1;
}
QMenuBar, QMenu, QToolBar {
    background-color: #073642;
}
QTableWidget, QTreeView, QListWidget, QTextEdit, QPlainTextEdit {
    background-color: #073642;
    color: #93a1a1;
}
"""

MONOKAI_THEME = """
/* Monokai theme */
QWidget {
    background-color: #272822;
    color: #f8f8f2;
}
QMenuBar, QMenu, QToolBar {
    background-color: #383830;
}
QTableWidget, QTreeView, QListWidget, QTextEdit, QPlainTextEdit {
    background-color: #49483e;
    color: #f8f8f2;
}
"""

class Plugin(PluginBase):
    """
    Plugin to add theme switching functionality.
    """
    def __init__(self):
        super().__init__()
        self.name = "Theme Switcher"
        self.description = "Adds menu items to switch between light, dark, and extra themes."
        self.main_window = None
        self.themes = [
            ("Light", LIGHT_THEME),
            ("Dark", DARK_THEME),
            ("Solarized Dark", SOLARIZED_DARK_THEME),
            ("Monokai", MONOKAI_THEME)
        ]
        self.current_theme_index = 1  # Default to Dark

    def initialize_ui(self, main_window):
        """Add theme switcher to the menu bar."""
        self.main_window = main_window
        if not hasattr(main_window, 'menuBar'):
            logger.error("MainWindow has no menuBar")
            return
        menubar = main_window.menuBar()
        view_menu = None
        for action in menubar.actions():
            menu = action.menu()
            if menu and action.text().lower().startswith("&view"):
                view_menu = menu
        if not view_menu:
            view_menu = QtWidgets.QMenu("&View", main_window)
            menubar.addMenu(view_menu)
        # Add theme submenu
        self.theme_menu = QtWidgets.QMenu("Switch Theme", main_window)
        self.theme_actions = []
        for idx, (theme_name, _) in enumerate(self.themes):
            action = QAction(theme_name, main_window)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, i=idx: self.set_theme(i))
            self.theme_menu.addAction(action)
            self.theme_actions.append(action)
        view_menu.addMenu(self.theme_menu)
        # Set initial theme
        self.set_theme(self.current_theme_index)
        logger.info(f"Theme Switcher plugin initialized with {self.themes[self.current_theme_index][0]} theme")

    def set_theme(self, theme_index):
        if not self.main_window:
            logger.warning("Theme Switcher plugin: main_window is None, cannot apply theme.")
            return
        self.current_theme_index = theme_index
        theme_name, theme_style = self.themes[theme_index]
        self.main_window.setStyleSheet(theme_style)
        for idx, action in enumerate(self.theme_actions):
            action.setChecked(idx == theme_index)
        logger.info(f"Switched to {theme_name} theme")

    def toggle_theme(self):
        next_index = (self.current_theme_index + 1) % len(self.themes)
        self.set_theme(next_index)

    def get_settings_widget(self):
        # Create a widget for the Preferences dialog
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel("Select Application Theme:")
        layout.addWidget(label)
        self.button_group = QButtonGroup(widget)
        for idx, (theme_name, _) in enumerate(self.themes):
            btn = QRadioButton(theme_name)
            self.button_group.addButton(btn, idx)
            layout.addWidget(btn)
            if idx == self.current_theme_index:
                btn.setChecked(True)
        self.button_group.buttonClicked[int].connect(self.set_theme)
        return widget
