import logging
import sys
from pathlib import Path
import webbrowser # Fallback if QDesktopServices fails

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QDesktopServices
from PySide6.QtCore import Qt, Slot, QUrl

# Import Plugin Base
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

class Plugin(PluginBase):
    """
    Adds a context menu item to the project list to open its folder in the file explorer.
    """
    def __init__(self):
        super().__init__()
        self.name = "Open Project Folder"
        self.description = "Right-click a project in the sidebar list to open its folder."
        self.version = "1.0.0"
        self.main_window = None
        self.project_list_widget = None

    def initialize_ui(self, main_window):
        """Find the project list and add context menu handling."""
        self.main_window = main_window

        if not hasattr(main_window, 'project_list'):
            logger.error(f"'{self.name}' plugin: MainWindow is missing 'project_list' attribute. Cannot initialize.")
            return

        self.project_list_widget = main_window.project_list
        if not isinstance(self.project_list_widget, QtWidgets.QListWidget):
             logger.error(f"'{self.name}' plugin: MainWindow.project_list is not a QListWidget. Cannot initialize.")
             self.project_list_widget = None # Ensure it's None if wrong type
             return

        # Crucial: Enable custom context menus for the QListWidget
        self.project_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)

        # Connect the signal
        try:
            self.project_list_widget.customContextMenuRequested.connect(self._show_project_context_menu)
            logger.info(f"{self.name} plugin initialized UI and connected context menu.")
        except Exception as e:
            logger.error(f"Error connecting context menu signal for {self.name}: {e}", exc_info=True)
            self.project_list_widget = None # Disable if connection failed

    @Slot(QtCore.QPoint)
    def _show_project_context_menu(self, position):
        """Create and show the context menu when right-clicking the project list."""
        if not self.project_list_widget:
            return # Safety check

        # Get the item under the cursor
        item = self.project_list_widget.itemAt(position)
        if not item:
            return # Clicked on empty area

        # Get project data associated with the item
        project_data = item.data(Qt.UserRole)
        if not isinstance(project_data, dict) or 'path' not in project_data:
            logger.warning(f"No valid project data found for selected item: {item.text()}")
            return # No data or path stored

        project_path = project_data.get('path')
        project_name = project_data.get('name', item.text()) # Use item text as fallback name

        # Create the menu
        menu = QtWidgets.QMenu()
        icon = QIcon.fromTheme("folder-open", QIcon.fromTheme("document-open")) # Try folder first, then generic open
        open_action = QAction(icon, f"Open Folder for '{project_name}'", menu)

        # Use lambda to pass the specific path to the slot when triggered
        open_action.triggered.connect(lambda checked=False, path=project_path: self._open_project_folder(path))

        menu.addAction(open_action)

        # Show the menu at the cursor's global position
        menu.exec(self.project_list_widget.viewport().mapToGlobal(position))

    @Slot(str)
    def _open_project_folder(self, path_str):
        """Opens the given path in the system's file explorer."""
        if not path_str:
            logger.error("Attempted to open folder, but path was empty.")
            return

        folder_path = Path(path_str)
        logger.info(f"Attempting to open project folder: {folder_path}")

        if not folder_path.exists() or not folder_path.is_dir():
            logger.warning(f"Project folder does not exist or is not a directory: {folder_path}")
            QtWidgets.QMessageBox.warning(
                self.main_window,
                "Folder Not Found",
                f"The project folder could not be found:\n{folder_path}"
            )
            return

        # Use QDesktopServices for cross-platform opening
        url = QUrl.fromLocalFile(str(folder_path.resolve())) # Use resolved absolute path
        if not QDesktopServices.openUrl(url):
            logger.error(f"QDesktopServices failed to open URL: {url.toString()}")
            # Fallback attempt using webbrowser (less reliable for folders on all platforms)
            try:
                 webbrowser.open(f"file:///{folder_path.resolve()}")
                 logger.info("Opened folder using webbrowser fallback.")
            except Exception as wb_err:
                 logger.error(f"webbrowser fallback failed: {wb_err}")
                 QtWidgets.QMessageBox.critical(
                    self.main_window,
                    "Error Opening Folder",
                    f"Could not open the project folder using system services or webbrowser:\n{folder_path}"
                 )

    def on_app_exit(self):
        """Disconnect signal if needed (usually not strictly necessary for context menus)."""
        try:
            if self.project_list_widget:
                self.project_list_widget.customContextMenuRequested.disconnect(self._show_project_context_menu)
                logger.info(f"{self.name} disconnected signals.")
        except (TypeError, RuntimeError) as e:
             # Ignore errors if already disconnected or widget deleted
            logger.debug(f"Error disconnecting signal for {self.name} (might be harmless): {e}")
        logger.info(f"{self.name} plugin exiting.")