# plugins/stats_statusbar_plugin.py
import logging
import json
from pathlib import Path
import os

from PySide6 import QtCore, QtWidgets
# *** Import QObject and QEvent separately ***
from PySide6.QtCore import Qt, Slot, Signal, QObject, QEvent
from PySide6.QtGui import QIcon, QColor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QDialogButtonBox, QMessageBox

from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- DEFAULT_CONFIG and CONFIG_PATH remain the same ---
DEFAULT_CONFIG = {
    "show_start": True,
    "show_finish": True,
    "show_errors": True,
    "message_format_start": "▶️ Running: {project}/{spider}...",
    "message_format_finish": "{icon} Finished: {project}/{spider} - {status_text}",
    "timeout": 5000,
    "history_size": 20
}
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = BASE_DIR / "config" / "stats_statusbar_plugin.json"


# *** --- NEW: Helper class for event filtering --- ***
class StatusBarEventHandler(QObject):
    def __init__(self, plugin_instance, parent=None):
        super().__init__(parent)
        self.plugin = plugin_instance # Store reference to the main plugin

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Use self.plugin to access main window, history, methods etc.
        if watched == self.plugin.main_window.statusBar():
            if event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    if self.plugin.history:
                        last = self.plugin.history[-1]
                        spider = last.get("spider")
                        # Access analytics plugin via self.plugin._analytics_plugin
                        if self.plugin._analytics_plugin and hasattr(self.plugin._analytics_plugin, 'show_analytics') and spider:
                            logger.debug(f"Left-click on status bar. Opening analytics (last spider: {spider})")
                            self.plugin._analytics_plugin.show_analytics()
                        elif not self.plugin._analytics_plugin:
                             logger.debug("Left-click on status bar, but analytics plugin not found.")
                        else:
                             logger.debug("Left-click on status bar, no spider context in last message or no history.")
                    return False # Let default processing continue

                elif event.button() == Qt.MouseButton.RightButton:
                    logger.debug("Right-click on status bar. Showing history popup.")
                    # Call the history popup method on the plugin instance
                    self.plugin._show_history_popup()
                    return True # Consume the right-click

        # Pass the event on (standard practice)
        return super().eventFilter(watched, event)
# *** --- END Helper class --- ***


# *** --- Plugin class NO LONGER inherits QObject --- ***
class Plugin(PluginBase):
    """
    Displays basic spider start/finish status in the main window's status bar.
    Now supports customization, message history, and analytics integration.
    """
    def __init__(self):
        # *** --- Call ONLY PluginBase constructor --- ***
        super().__init__()

        self.name = "Status Bar Stats"
        self.description = "Shows simple spider start/finish messages in the status bar."
        self.version = "1.1.0" # Assuming version 1.1.0 from previous fix
        self.main_window = None
        self.config = DEFAULT_CONFIG.copy()
        self.history = []
        self._analytics_plugin = None # Initialize here
        self.event_handler = None     # Initialize event handler reference
        self._load_config()

    # --- _load_config and _save_config remain the same ---
    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.config.update(data)
        except Exception as e:
            logger.error(f"Failed to load stats statusbar plugin config: {e}")

    def _save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save stats statusbar plugin config: {e}")

    def initialize_ui(self, main_window):
        """Store main window reference and install event filter via helper."""
        self.main_window = main_window
        if not hasattr(main_window, 'statusBar'):
            logger.error(f"'{self.name}' plugin: MainWindow is missing 'statusBar' attribute. Plugin disabled.")
            self.main_window = None
            return # Stop initialization if no status bar

        logger.info(f"{self.name} plugin initialized.")

        # Find analytics plugin
        self._analytics_plugin = self._find_analytics_plugin()

        # *** --- Create and install the event handler object --- ***
        try:
            # Pass 'self' (the plugin instance) to the handler
            self.event_handler = StatusBarEventHandler(self, self.main_window.statusBar())
            # Install the *handler* object, not the plugin object
            self.main_window.statusBar().installEventFilter(self.event_handler)
            logger.info(f"Event filter installed on status bar via helper.")
        except Exception as e:
            logger.error(f"Failed to create or install StatusBarEventHandler: {e}", exc_info=True)
            self.event_handler = None # Ensure it's None if failed

    # --- _find_analytics_plugin remains the same ---
    def _find_analytics_plugin(self):
        if hasattr(self.main_window, "plugin_manager"):
            for plugin in self.main_window.plugin_manager.get_plugins().values():
                # Use getattr for safe access to 'name' attribute
                if getattr(plugin, "name", "") == "Spider Analytics":
                    logger.debug("Found Spider Analytics plugin.")
                    return plugin
        logger.debug("Spider Analytics plugin not found.")
        return None

    # --- eventFilter method is REMOVED from Plugin class ---

    # --- _add_to_history remains the same ---
    def _add_to_history(self, message, spider=None, project=None, event_type=None):
        entry = {
            "message": message,
            "spider": spider,
            "project": project,
            "event_type": event_type
        }
        self.history.append(entry)
        max_history = self.config.get("history_size", 20)
        if len(self.history) > max_history:
            self.history = self.history[-max_history:]

    # --- _show_history_popup remains the same (uses self.main_window, self.history) ---
    def _show_history_popup(self):
        if not self.history:
            logger.info("No status bar history to display.")
            return

        dlg = QDialog(self.main_window) # Use QDialog
        dlg.setWindowTitle("Status Bar Message History")
        dlg.setMinimumWidth(400)
        dlg.setMinimumHeight(200)
        layout = QVBoxLayout(dlg) # Use QVBoxLayout
        list_widget = QListWidget() # Use QListWidget
        for entry in reversed(self.history):
            list_widget.addItem(entry["message"])
        layout.addWidget(list_widget)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok) # Use QDialogButtonBox
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec()


    # --- on_spider_started / on_spider_finished remain the same ---
    # They correctly use invokeMethod to update the UI thread-safely
    def on_spider_started(self, spider_info):
        if not self.main_window or not self.config.get("show_start", True):
            return

        spider_name = spider_info.get('spider_name', 'UnknownSpider')
        project_name = spider_info.get('project_name', 'UnknownProject')
        fmt = self.config.get("message_format_start", DEFAULT_CONFIG["message_format_start"])
        message = fmt.format(project=project_name, spider=spider_name)
        self._add_to_history(message, spider=spider_name, project=project_name, event_type="start")

        try:
            QtCore.QMetaObject.invokeMethod(
                self.main_window.statusBar(),
                "showMessage",
                Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, message),
                QtCore.Q_ARG(int, 0)
            )
            logger.debug(f"{self.name}: Displayed start message: {message}")
        except Exception as e:
            logger.error(f"Error showing status bar message for spider start: {e}", exc_info=True)

    def on_spider_finished(self, spider_info, status, item_count):
        if not self.main_window or not self.config.get("show_finish", True):
            return

        spider_name = spider_info.get('spider_name', 'UnknownSpider')
        project_name = spider_info.get('project_name', 'UnknownProject')

        status_icon = "✅"
        status_text = status.capitalize()
        event_type = "finish"

        if "fail" in status.lower() or "error" in status.lower() or "killed" in status.lower() or "stopped" in status.lower():
            status_icon = "❌"
            event_type = "error"
        elif status == 'completed' and item_count == 0:
            status_icon = "⚠️"
            status_text = "Completed (0 items)"
        elif status == 'completed':
            status_text = f"Completed ({item_count} items)"

        fmt = self.config.get("message_format_finish", DEFAULT_CONFIG["message_format_finish"])
        message = fmt.format(
            icon=status_icon,
            project=project_name,
            spider=spider_name,
            status_text=status_text
        )
        self._add_to_history(message, spider=spider_name, project=project_name, event_type=event_type)

        if event_type == "error" and not self.config.get("show_errors", True):
            return

        try:
             timeout = int(self.config.get("timeout", DEFAULT_CONFIG["timeout"]))
        except (ValueError, TypeError):
             timeout = DEFAULT_CONFIG["timeout"]

        try:
            QtCore.QMetaObject.invokeMethod(
                self.main_window.statusBar(),
                "showMessage",
                Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, message),
                QtCore.Q_ARG(int, timeout)
            )
            logger.debug(f"{self.name}: Displayed finish message: {message}")
        except Exception as e:
            logger.error(f"Error showing status bar message for spider finish: {e}", exc_info=True)

    # --- on_app_exit and _create_settings_widget remain the same ---
    def on_app_exit(self):
        self._save_config()
        logger.info(f"{self.name} plugin exiting.")

    def _create_settings_widget(self):
        # This method doesn't change, it just returns a configuration widget
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(widget)

        show_start_cb = QtWidgets.QCheckBox("Show spider start messages")
        show_start_cb.setChecked(self.config.get("show_start", True))
        show_finish_cb = QtWidgets.QCheckBox("Show spider finish messages")
        show_finish_cb.setChecked(self.config.get("show_finish", True))
        show_errors_cb = QtWidgets.QCheckBox("Show error messages")
        show_errors_cb.setChecked(self.config.get("show_errors", True))

        layout.addRow(show_start_cb)
        layout.addRow(show_finish_cb)
        layout.addRow(show_errors_cb)

        msg_fmt_start = QtWidgets.QLineEdit(self.config.get("message_format_start", DEFAULT_CONFIG["message_format_start"]))
        msg_fmt_finish = QtWidgets.QLineEdit(self.config.get("message_format_finish", DEFAULT_CONFIG["message_format_finish"]))
        layout.addRow("Start message format:", msg_fmt_start)
        layout.addRow("Finish message format:", msg_fmt_finish)

        timeout_spin = QtWidgets.QSpinBox()
        timeout_spin.setRange(1000, 60000)
        timeout_spin.setValue(int(self.config.get("timeout", DEFAULT_CONFIG["timeout"])))
        timeout_spin.setSuffix(" ms")
        layout.addRow("Message timeout:", timeout_spin)

        history_spin = QtWidgets.QSpinBox()
        history_spin.setRange(5, 100)
        history_spin.setValue(int(self.config.get("history_size", DEFAULT_CONFIG["history_size"])))
        layout.addRow("History size:", history_spin)

        view_history_btn = QtWidgets.QPushButton("View Message History")
        # Connect to the method on the *plugin* instance, not the handler
        view_history_btn.clicked.connect(self._show_history_popup)
        layout.addRow(view_history_btn)

        def save_settings():
            self.config["show_start"] = show_start_cb.isChecked()
            self.config["show_finish"] = show_finish_cb.isChecked()
            self.config["show_errors"] = show_errors_cb.isChecked()
            self.config["message_format_start"] = msg_fmt_start.text()
            self.config["message_format_finish"] = msg_fmt_finish.text()
            self.config["timeout"] = timeout_spin.value()
            self.config["history_size"] = history_spin.value()
            self._save_config()

        show_start_cb.stateChanged.connect(save_settings)
        show_finish_cb.stateChanged.connect(save_settings)
        show_errors_cb.stateChanged.connect(save_settings)
        msg_fmt_start.editingFinished.connect(save_settings)
        msg_fmt_finish.editingFinished.connect(save_settings)
        timeout_spin.valueChanged.connect(save_settings)
        history_spin.valueChanged.connect(save_settings)

        help_label = QtWidgets.QLabel(
            "Placeholders: {project}, {spider}, {icon}, {status_text}\n"
            "Left-click status bar to open analytics for last spider. Right-click to view message history."
        )
        help_label.setWordWrap(True)
        layout.addRow(help_label)

        return widget