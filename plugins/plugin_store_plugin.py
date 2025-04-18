import logging
import sys
import json
import os
import threading
import re
from pathlib import Path
import webbrowser # Import webbrowser

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QColor, QDesktopServices # Added QDesktopServices
from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtCore import Qt, Slot, Signal, QObject, QThread, QUrl # Added QUrl

# Import Plugin Base
from app.plugin_base import PluginBase

# --- Dependency Checks ---
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.warning("Plugin Store: 'requests' library not found. Please install it (`pip install requests`). Network features will be disabled.")

try:
    from packaging.version import parse as parse_version, InvalidVersion
    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False
    logging.warning("Plugin Store: 'packaging' library not found (`pip install packaging`). Version comparison will be basic string comparison.")

logger = logging.getLogger(__name__)

# --- Configuration ---
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CATALOG_PATH = BASE_DIR / "config" / "plugin_store_catalog.json"
DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/RedHotBallBag/spiderplugins/refs/heads/main/plugin_catalog.json" # Replace with your actual catalog URL

# --- Worker (Remains the same) ---
class NetworkWorker(QObject):
    catalog_fetched = Signal(list)
    download_finished = Signal(bool, str, str) # success, filename, content
    error_occurred = Signal(str)

    def __init__(self, catalog_url):
        super().__init__()
        self.catalog_url = catalog_url

    @Slot()
    def fetch_catalog(self):
        if not REQUESTS_AVAILABLE:
            self.error_occurred.emit("Network library ('requests') is missing.")
            return
        try:
            logger.info(f"Fetching plugin catalog from: {self.catalog_url}")
            response = requests.get(self.catalog_url, timeout=15)
            response.raise_for_status()
            catalog_data = response.json()
            if not isinstance(catalog_data, list):
                 raise ValueError("Catalog format is invalid (expected a JSON list).")
            logger.info(f"Successfully fetched {len(catalog_data)} entries from catalog.")
            self.catalog_fetched.emit(catalog_data)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching catalog: {e}")
            self.error_occurred.emit(f"Network Error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding catalog JSON: {e}")
            try:
                raw_text = requests.get(self.catalog_url, timeout=5).text[:500]
                error_details = f"Catalog Format Error: {e}\nNear: ...{raw_text}..."
            except Exception:
                error_details = f"Catalog Format Error: {e}"
            self.error_occurred.emit(error_details)
        except ValueError as e:
             logger.error(f"Catalog validation error: {e}")
             self.error_occurred.emit(f"Catalog Error: {e}")
        except Exception as e:
            logger.exception("Unexpected error fetching catalog:")
            self.error_occurred.emit(f"Unexpected Error: {e}")

    @Slot(str, str)
    def download_plugin(self, download_url, filename):
        if not REQUESTS_AVAILABLE:
            self.error_occurred.emit("Network library ('requests') is missing.")
            return
        try:
            logger.info(f"Downloading plugin '{filename}' from: {download_url}")
            response = requests.get(download_url, timeout=30)
            response.raise_for_status()
            content = response.text
            logger.info(f"Successfully downloaded plugin '{filename}' ({len(content)} bytes).")
            self.download_finished.emit(True, filename, content)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error downloading plugin {filename}: {e}")
            self.error_occurred.emit(f"Download Error for {filename}: {e}")
            self.download_finished.emit(False, filename, "")
        except Exception as e:
            logger.exception(f"Unexpected error downloading plugin {filename}:")
            self.error_occurred.emit(f"Download Error for {filename}: {e}")
            self.download_finished.emit(False, filename, "")


# --- Changelog Dialog ---
class ChangelogDialog(QtWidgets.QDialog):
    def __init__(self, plugin_name, version, changelog, release_url=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Changelog for {plugin_name} v{version}")
        self.setMinimumWidth(450)
        self.setMinimumHeight(300)

        layout = QtWidgets.QVBoxLayout(self)

        text_browser = QtWidgets.QTextBrowser()
        text_browser.setPlainText(changelog if changelog else "No changelog details provided.")
        text_browser.setOpenExternalLinks(True) # Allow opening links if any in text
        layout.addWidget(text_browser)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        if release_url:
            view_online_button = QtWidgets.QPushButton("View Online")
            view_online_button.setIcon(QIcon.fromTheme("browser"))
            view_online_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release_url)))
            button_layout.addWidget(view_online_button)

        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)


# --- Plugin Store Dialog ---
class PluginStoreDialog(QtWidgets.QDialog):
    # ( __init__ remains the same )
    def __init__(self, plugins_dir, catalog_url, parent=None):
        super().__init__(parent)
        self.plugins_dir = Path(plugins_dir)
        self.catalog_url = catalog_url
        self.catalog_data = []
        self.installed_plugins = self._get_installed_plugins()
        self.worker = None
        self.thread = None

        self.setWindowTitle("Plugin Store")
        self.setMinimumSize(700, 500)

        self._init_ui()
        self._refresh_catalog() # Fetch on open

    # ( _init_ui remains the same )
    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        toolbar = QtWidgets.QHBoxLayout()
        refresh_button = QtWidgets.QPushButton("Refresh List")
        refresh_button.setIcon(QIcon.fromTheme("view-refresh"))
        refresh_button.clicked.connect(self._refresh_catalog)
        self.status_label = QtWidgets.QLabel("Fetching catalog...")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Name", "Description", "Author", "Version", "Status", "Action"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.table.setEnabled(False)

    # ( _get_installed_plugins remains the same )
    def _get_installed_plugins(self):
        installed = set()
        if self.plugins_dir.exists():
            try:
                for item in self.plugins_dir.iterdir():
                    if item.is_file() and item.suffix == '.py' and item.name != '__init__.py':
                        installed.add(item.name)
            except OSError as e:
                logger.error(f"Error listing installed plugins in {self.plugins_dir}: {e}")
        return installed

    # ( _refresh_catalog remains the same )
    @Slot()
    def _refresh_catalog(self):
        if not REQUESTS_AVAILABLE:
             self.status_label.setText("<font color='red'>Error: 'requests' library missing.</font>")
             QMessageBox.critical(self, "Missing Dependency", "The 'requests' library is required for the Plugin Store. Please install it (`pip install requests`).")
             return

        if self.thread and self.thread.isRunning():
            logger.warning("Catalog fetch already in progress.")
            return

        self.status_label.setText("Fetching catalog...")
        self.table.setEnabled(False)
        self.table.setRowCount(0)

        self.thread = QThread(self)
        self.worker = NetworkWorker(self.catalog_url)
        self.worker.moveToThread(self.thread)

        self.worker.catalog_fetched.connect(self._populate_table)
        self.worker.error_occurred.connect(self._handle_network_error)
        self.thread.started.connect(self.worker.fetch_catalog)
        self.worker.catalog_fetched.connect(self.thread.quit)
        self.worker.error_occurred.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: setattr(self, 'thread', None))
        self.thread.finished.connect(lambda: setattr(self, 'worker', None))

        self.thread.start()

    # ( _get_local_plugin_version remains the same )
    def _get_local_plugin_version(self, filename):
        if not PACKAGING_AVAILABLE:
            return None

        local_path = self.plugins_dir / filename
        if not local_path.exists():
            return None

        try:
            content = local_path.read_text(encoding='utf-8', errors='ignore')
            match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
            if match:
                version_str = match.group(1)
                try:
                    parse_version(version_str)
                    logger.debug(f"Found local version {version_str} for {filename}")
                    return version_str
                except InvalidVersion:
                    logger.warning(f"Found invalid version string '{version_str}' in {filename}")
                    return None
            else:
                logger.warning(f"Could not find version string in {filename}")
                return None
        except Exception as e:
            logger.error(f"Error reading or parsing local plugin {filename} for version: {e}")
            return None

    @Slot(list)
    def _populate_table(self, catalog_data):
        """Fills the table with data, checking versions for installed plugins."""
        logger.debug("Populating plugin store table with version checks.")
        self.catalog_data = catalog_data
        self.installed_plugins = self._get_installed_plugins()
        self.table.setRowCount(0)
        self.table.setEnabled(True)

        if not catalog_data:
            self.status_label.setText("Catalog is empty or invalid.")
            return

        self.table.setRowCount(len(catalog_data))
        for row, plugin_info in enumerate(catalog_data):
            filename = plugin_info.get("filename")
            remote_version_str = plugin_info.get("version")
            status = "Not Installed"
            action_text = "Install"
            action_enabled = True
            action_slot = self._install_plugin # Default action
            status_color = None
            is_update = False # Flag to know if it's an update

            if filename in self.installed_plugins:
                local_version_str = self._get_local_plugin_version(filename)
                if local_version_str and remote_version_str and PACKAGING_AVAILABLE:
                    try:
                        local_ver = parse_version(local_version_str)
                        remote_ver = parse_version(remote_version_str)

                        if remote_ver > local_ver:
                            # --- Version display fixed here ---
                            status = f"Installed v{local_version_str} (Update available)"
                            action_text = "Update"
                            action_slot = self._install_plugin # Update uses install logic
                            status_color = QColor("orange")
                            is_update = True # Mark as update for changelog check
                        elif remote_ver == local_ver:
                            status = f"Installed (v{local_version_str})"
                            action_text = "Uninstall"
                            action_slot = self._uninstall_plugin
                            status_color = QColor("darkgreen")
                        else: # Local version is newer? (Shouldn't happen often with remote catalog)
                             status = f"Installed v{local_version_str} (Newer)"
                             action_text = "Reinstall Catalog Ver" # Offer downgrade/reinstall
                             action_slot = self._install_plugin
                             status_color = QColor("purple")

                    except InvalidVersion:
                        status = "Installed (Version Error)"
                        action_text = "Reinstall"
                        action_slot = self._install_plugin
                        status_color = QColor("red")
                elif local_version_str:
                     status = f"Installed (v{local_version_str})"
                     action_text = "Uninstall"
                     action_slot = self._uninstall_plugin
                     status_color = QColor("darkgreen")
                else:
                    status = "Installed (Unknown Ver.)"
                    action_text = "Reinstall"
                    action_slot = self._install_plugin
                    status_color = QColor("gray")

            # --- Populate Table Cells ---
            self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(plugin_info.get("name", "N/A")))
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(plugin_info.get("description", "")))
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(plugin_info.get("author", "N/A")))
            self.table.setItem(row, 3, QtWidgets.QTableWidgetItem(remote_version_str or "N/A"))

            status_item = QtWidgets.QTableWidgetItem(status)
            if status_color:
                 status_item.setForeground(status_color)
            self.table.setItem(row, 4, status_item)

            # --- Action Button Cell ---
            action_button = QtWidgets.QPushButton(action_text)
            action_button.setEnabled(action_enabled)
            # Store data needed for the action AND if it's an update
            action_button.setProperty("plugin_data", plugin_info)
            action_button.setProperty("is_update", is_update)
            action_button.clicked.connect(action_slot)
            self.table.setCellWidget(row, 5, action_button)

        self.table.resizeRowsToContents()
        self.status_label.setText(f"Catalog refreshed. {len(catalog_data)} plugins available.")

    # ( _handle_network_error, _on_selection_changed remain the same )
    @Slot(str)
    def _handle_network_error(self, error_message):
        self.status_label.setText(f"<font color='red'>Error: {error_message}</font>")
        self.table.setEnabled(False)
        QMessageBox.warning(self, "Plugin Store Error", f"Could not fetch or process plugin catalog:\n{error_message}")

    @Slot()
    def _on_selection_changed(self):
        pass # Not currently used

    @Slot()
    def _install_plugin(self):
        """Handles the Install/Update/Reinstall button click."""
        sender_button = self.sender()
        if not sender_button: return
        plugin_data = sender_button.property("plugin_data")
        is_update = sender_button.property("is_update") # Get the update flag
        if not plugin_data: return

        download_url = plugin_data.get("download_url")
        filename = plugin_data.get("filename")
        plugin_name = plugin_data.get('name')
        remote_version = plugin_data.get('version')
        changelog = plugin_data.get('changelog')
        release_url = plugin_data.get('release_notes_url')

        if not download_url or not filename:
            QMessageBox.critical(self, "Error", "Missing download URL or filename in catalog data.")
            return

        # --- Show Changelog if Updating ---
        if is_update and (changelog or release_url):
             changelog_text = changelog if changelog else f"View release notes online for version {remote_version}."
             changelog_dialog = ChangelogDialog(plugin_name, remote_version, changelog_text, release_url, self)
             changelog_dialog.exec() # Show changelog modally first

        # --- Confirmation ---
        is_update_or_reinstall = (self.plugins_dir / filename).exists()
        action_word = "Update" if is_update else ("Reinstall" if is_update_or_reinstall else "Install")

        reply = QMessageBox.question(
            self, f"Confirm {action_word}",
            f"{action_word} plugin '{plugin_name}' to v{remote_version} ({filename})?\n\n"
            f"{'This will overwrite the existing version.' if is_update_or_reinstall else ''}\n"
            "Note: Installing plugins involves downloading code. Only install from trusted sources.\n"
            "You will need to restart the application to load/update the plugin.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        # --- Proceed with Download (Threaded) ---
        self.status_label.setText(f"Downloading {filename}...")
        sender_button.setEnabled(False)
        QApplication.processEvents()

        self.thread = QThread(self)
        self.worker = NetworkWorker(self.catalog_url)
        self.worker.moveToThread(self.thread)

        self.worker.download_finished.connect(self._save_plugin)
        self.worker.error_occurred.connect(self._handle_network_error)
        self.thread.started.connect(lambda: self.worker.download_plugin(download_url, filename))
        # Cleanup connections
        self.worker.download_finished.connect(self.thread.quit)
        self.worker.error_occurred.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: setattr(self, 'thread', None))
        self.thread.finished.connect(lambda: setattr(self, 'worker', None))
        self.thread.finished.connect(lambda: sender_button.setEnabled(True)) # Re-enable button

        self.thread.start()

    # ( _save_plugin remains the same )
    @Slot(bool, str, str)
    def _save_plugin(self, success, filename, content):
        if not success:
            self.status_label.setText(f"<font color='red'>Download failed for {filename}.</font>")
            return

        target_path = self.plugins_dir / filename
        try:
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Plugin '{filename}' saved successfully to {target_path}")
            self.status_label.setText(f"'{filename}' installed/updated. Restart required.")
            QMessageBox.information(self, "Operation Complete",
                                    f"Plugin '{filename}' saved successfully.\n\nPlease restart the application to load it.")
            self._refresh_catalog()

        except OSError as e:
            logger.error(f"Error saving plugin file {target_path}: {e}")
            QMessageBox.critical(self, "File Error", f"Could not save plugin file:\n{e}")
            self.status_label.setText(f"<font color='red'>Error saving {filename}.</font>")
        except Exception as e:
             logger.exception(f"Unexpected error saving plugin {filename}:")
             QMessageBox.critical(self, "Error", f"An unexpected error occurred saving the plugin:\n{e}")
             self.status_label.setText(f"<font color='red'>Error saving {filename}.</font>")


    # ( _uninstall_plugin remains the same )
    @Slot()
    def _uninstall_plugin(self):
        sender_button = self.sender()
        if not sender_button: return
        plugin_data = sender_button.property("plugin_data")
        if not plugin_data: return

        filename = plugin_data.get("filename")
        if not filename:
            QMessageBox.critical(self, "Error", "Missing filename in plugin data.")
            return

        target_path = self.plugins_dir / filename

        if not target_path.exists():
            QMessageBox.warning(self, "Not Found", f"Plugin file '{filename}' not found in {self.plugins_dir}. Refreshing list.")
            self._refresh_catalog()
            return

        reply = QMessageBox.question(
            self, "Confirm Uninstall",
            f"Are you sure you want to uninstall plugin '{plugin_data.get('name')}' ({filename})?\n\n"
            "You will need to restart the application for the change to take effect.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        try:
            target_path.unlink()
            logger.info(f"Uninstalled plugin file: {target_path}")
            self.status_label.setText(f"'{filename}' uninstalled. Restart required.")
            QMessageBox.information(self, "Uninstall Complete",
                                    f"Plugin '{filename}' uninstalled successfully.\n\nPlease restart the application.")
            self._refresh_catalog()

        except OSError as e:
            logger.error(f"Error deleting plugin file {target_path}: {e}")
            QMessageBox.critical(self, "File Error", f"Could not delete plugin file:\n{e}")
            self.status_label.setText(f"<font color='red'>Error uninstalling {filename}.</font>")
        except Exception as e:
            logger.exception(f"Unexpected error uninstalling plugin {filename}:")
            QMessageBox.critical(self, "Error", f"An unexpected error occurred uninstalling the plugin:\n{e}")
            self.status_label.setText(f"<font color='red'>Error uninstalling {filename}.</font>")

    # ( closeEvent remains the same )
    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            logger.warning("Closing Plugin Store dialog while network operation in progress. Attempting to stop thread.")
            self.thread.quit()
            self.thread.wait(1000)
        super().closeEvent(event)


# --- Plugin Class (remains mostly the same) ---
class Plugin(PluginBase):
    """
    Plugin to add a Plugin Store for discovering and installing plugins.
    """
    def __init__(self):
        super().__init__()
        self.name = "Plugin Store"
        self.description = "Discover, install, and update plugins from a remote catalog."
        self.version = "1.1.0" # Incremented version
        self.main_window = None
        self.catalog_url = DEFAULT_CATALOG_URL # Could be loaded from config

    def initialize_ui(self, main_window):
        """Add menu item to trigger the Plugin Store dialog."""
        self.main_window = main_window

        if not REQUESTS_AVAILABLE:
             logger.error(f"{self.name} requires the 'requests' library, but it's not installed. Plugin disabled.")
             return
        if not PACKAGING_AVAILABLE:
             logger.warning(f"{self.name}: 'packaging' library not found. Version checking will be limited.")

        if not hasattr(main_window, 'menuBar'):
            logger.error(f"{self.name}: Main window has no 'menuBar'. Skipping menu item add.")
            return

        menubar = main_window.menuBar()
        tools_menu_action = None
        for action in menubar.actions():
            if action.menu() and action.text().strip().replace('&','').lower() == "tools":
                tools_menu_action = action
                break

        if not tools_menu_action:
             logger.error(f"{self.name}: Could not find Tools menu action.")
             return

        tools_menu = tools_menu_action.menu()
        if not tools_menu:
             logger.error(f"{self.name}: Tools action found but has no QMenu.")
             return

        store_action = QAction(QIcon.fromTheme("system-software-install"), "Plugin Store...", main_window)
        store_action.triggered.connect(self._show_store_dialog)
        tools_menu.addAction(store_action)

        logger.info(f"{self.name} plugin initialized UI.")

    @Slot()
    def _show_store_dialog(self):
        """Shows the plugin store dialog."""
        plugins_dir = "plugins"
        if hasattr(self.main_window, 'plugin_manager') and hasattr(self.main_window.plugin_manager, 'plugins_dir'):
            plugins_dir = self.main_window.plugin_manager.plugins_dir
        else:
            logger.warning(f"{self.name}: Could not get plugins_dir from plugin_manager, using default '{plugins_dir}'.")

        dialog = PluginStoreDialog(plugins_dir, self.catalog_url, self.main_window)
        dialog.exec()


    def on_app_exit(self):
        """Placeholder for cleanup if needed."""
        logger.info(f"{self.name} plugin exiting.")