import logging
import sys
import json
import os
import ast  # For safer code analysis than compile()
import re
from pathlib import Path

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QTreeWidget, QTreeWidgetItem, QPushButton,
                               QDialogButtonBox, QMessageBox, QSizePolicy)
from PySide6.QtCore import Qt, Slot, QUrl

# Import Plugin Base
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Helper Function for Tree Items ---
def create_tree_item(text, icon_name=None, tooltip=None, file_path=None, line_number=None):
    """Creates a QTreeWidgetItem with optional icon and data."""
    item = QTreeWidgetItem([text]) # Only one column needed for description
    if icon_name:
        icon = QIcon.fromTheme(icon_name)
        if not icon.isNull(): # Check if icon was found
            item.setIcon(0, icon)
        else:
            logger.warning(f"Could not find standard icon: {icon_name}")
            # Optionally set text prefix like [E] or [W] as fallback
            prefix_map = {"dialog-error": "[E]", "dialog-warning": "[W]", "dialog-information": "[I]"}
            prefix = prefix_map.get(icon_name, "[?]")
            item.setText(0, f"{prefix} {text}")

    if tooltip:
        item.setToolTip(0, tooltip)
    if file_path:
        item.setData(0, Qt.UserRole, str(file_path)) # Store file path
        item.setData(0, Qt.UserRole + 1, line_number) # Store line number (can be None)
    return item

# --- Health Check Dialog ---
class HealthCheckDialog(QDialog):
    """Dialog to display project health check results."""

    # Signal emitted when a file item is double-clicked
    # Arguments: file_path (str), line_number (int or None)
    open_file_requested = QtCore.Signal(str, object)

    def __init__(self, project_name, results, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Health Check Results: {project_name}")
        self.setMinimumSize(650, 450)

        self._init_ui()
        self.populate_results(results)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Summary Label
        self.summary_label = QLabel("Running checks...")
        self.summary_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.summary_label)

        # Results Tree
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabel("Check Description")
        self.results_tree.setColumnCount(1)
        self.results_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.results_tree)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def populate_results(self, results):
        """Fills the tree widget with check results."""
        self.results_tree.clear()

        errors = results.get('errors', [])
        warnings = results.get('warnings', [])
        info = results.get('info', [])

        # --- Create Top-Level Categories ---
        errors_item = QTreeWidgetItem(self.results_tree, ["Errors"])
        errors_item.setIcon(0, QIcon.fromTheme("dialog-error"))
        errors_item.setExpanded(len(errors) > 0) # Expand if there are errors

        warnings_item = QTreeWidgetItem(self.results_tree, ["Warnings"])
        warnings_item.setIcon(0, QIcon.fromTheme("dialog-warning"))
        warnings_item.setExpanded(len(warnings) > 0 and len(errors) == 0) # Expand if warnings but no errors

        info_item = QTreeWidgetItem(self.results_tree, ["Information / Suggestions"])
        info_item.setIcon(0, QIcon.fromTheme("dialog-information"))
        info_item.setExpanded(len(errors) == 0 and len(warnings) == 0) # Expand if only info

        # --- Populate Items ---
        for err in errors:
            errors_item.addChild(create_tree_item(
                err['message'],
                icon_name="list-remove", # Smaller icon for item
                tooltip=err.get('details'),
                file_path=err.get('file'),
                line_number=err.get('line')
            ))

        for warn in warnings:
            warnings_item.addChild(create_tree_item(
                warn['message'],
                icon_name="emblem-important",
                tooltip=warn.get('details'),
                file_path=warn.get('file'),
                line_number=warn.get('line')
            ))

        for inf in info:
            info_item.addChild(create_tree_item(
                inf['message'],
                icon_name="edit-find",
                tooltip=inf.get('details'),
                file_path=inf.get('file'),
                line_number=inf.get('line')
            ))

        # --- Update Summary ---
        if errors:
            self.summary_label.setText("❌ Errors Found!")
            self.summary_label.setStyleSheet("font-weight: bold; font-size: 14px; color: red;")
        elif warnings:
            self.summary_label.setText("⚠️ Warnings Found.")
            self.summary_label.setStyleSheet("font-weight: bold; font-size: 14px; color: orange;")
        else:
            self.summary_label.setText("✅ Project looks healthy.")
            self.summary_label.setStyleSheet("font-weight: bold; font-size: 14px; color: green;")

        # Hide categories with no items
        errors_item.setHidden(len(errors) == 0)
        warnings_item.setHidden(len(warnings) == 0)
        info_item.setHidden(len(info) == 0)

        self.results_tree.resizeColumnToContents(0)


    @Slot(QTreeWidgetItem, int)
    def _on_item_double_clicked(self, item, column):
        """Emits signal to open file when an item with path data is double-clicked."""
        file_path = item.data(0, Qt.UserRole)
        line_number = item.data(0, Qt.UserRole + 1)
        if file_path:
            logger.info(f"Requesting to open file: {file_path} at line {line_number}")
            self.open_file_requested.emit(str(file_path), line_number)


# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Project Health Check plugin. Adds analysis for Scrapy projects.
    """
    def __init__(self):
        super().__init__()
        self.name = "Project Health Check"
        self.description = "Analyzes selected project for common issues and best practices."
        self.version = "1.0.0"
        self.main_window = None

    def initialize_ui(self, main_window):
        """Add menu item to trigger the health check dialog."""
        self.main_window = main_window

        if not hasattr(main_window, 'menuBar'):
            logger.error(f"{self.name}: MainWindow is missing 'menuBar'. Skipping menu item add.")
            return
        if not hasattr(main_window, 'project_controller'):
             logger.error(f"{self.name}: MainWindow is missing 'project_controller'. Skipping.")
             return

        menubar = main_window.menuBar()
        tools_menu_action = None
        for action in menubar.actions():
            if action.menu() and action.text().strip().replace('&','').lower() == "tools":
                tools_menu_action = action
                break

        if not tools_menu_action:
             logger.warning(f"{self.name}: Could not find Tools menu action. Creating one.")
             tools_menu = menubar.addMenu("&Tools")
        else:
             tools_menu = tools_menu_action.menu()

        if not tools_menu:
             logger.error(f"{self.name}: Failed to get or create Tools menu.")
             return

        health_action = QAction(QIcon.fromTheme("dialog-ok-apply", QIcon.fromTheme("health")), # Try health or check icon
                                "Check Project Health...", main_window)
        health_action.setToolTip("Run checks on the selected project for common issues.")
        health_action.triggered.connect(self._show_health_check_dialog)
        tools_menu.addAction(health_action)

        logger.info(f"{self.name} plugin initialized UI.")


    @Slot()
    def _show_health_check_dialog(self):
        """Gets the current project and shows the health check dialog."""
        if not self.main_window or not hasattr(self.main_window, 'current_project') or not self.main_window.current_project:
            QMessageBox.warning(self.main_window, "No Project", "Please select a project from the sidebar first.")
            return

        project_data = self.main_window.current_project
        project_path = Path(project_data.get('path', ''))
        project_name = project_data.get('name', 'Unknown Project')

        if not project_path or not project_path.is_dir():
            QMessageBox.critical(self.main_window, "Error", f"Invalid or missing path for project '{project_name}'.")
            return

        # Run checks (can be slow, consider threading for more complex checks later)
        try:
            results = self._run_checks(project_path, project_name)
        except Exception as e:
             logger.exception(f"Error running health checks for project {project_name}:")
             QMessageBox.critical(self.main_window, "Check Failed", f"An error occurred during the health check:\n{e}")
             return

        # Show dialog
        dialog = HealthCheckDialog(project_name, results, self.main_window)
        # Connect the signal from the dialog to a method in the main window
        if hasattr(self.main_window, '_open_file'):
             # Use lambda to adapt signal if _open_file doesn't take line number
             # dialog.open_file_requested.connect(lambda path, line: self.main_window._open_file(path))
             # Or if _open_file can handle it (better):
             dialog.open_file_requested.connect(self._request_open_file) # Connect to a slot in *this* plugin
        else:
             logger.warning("Main window does not have '_open_file' method. Double-click navigation disabled.")

        dialog.exec()

    @Slot(str, object) # Receives file_path (str) and line_number (int or None)
    def _request_open_file(self, file_path, line_number):
         """Handles the request to open a file from the dialog."""
         if not self.main_window or not hasattr(self.main_window, '_open_file'):
              return

         success = self.main_window._open_file(file_path)

         # Optional: Add logic to jump to the line number if editor supports it
         if success and line_number is not None and hasattr(self.main_window, 'code_editor'):
              try:
                  editor = self.main_window.code_editor
                  cursor = editor.textCursor()
                  # Move cursor to the start of the specified line number (1-based index)
                  cursor.movePosition(QtGui.QTextCursor.Start)
                  cursor.movePosition(QtGui.QTextCursor.Down, QtGui.QTextCursor.MoveAnchor, line_number - 1)
                  editor.setTextCursor(cursor)
                  editor.ensureCursorVisible()
                  logger.info(f"Moved editor cursor to line {line_number} in {Path(file_path).name}")
              except Exception as e:
                  logger.warning(f"Could not move cursor to line {line_number}: {e}")


    def _run_checks(self, project_path: Path, project_name: str):
        """Performs various checks on the project files."""
        logger.info(f"Running health checks for project: {project_name} at {project_path}")
        results = {'errors': [], 'warnings': [], 'info': []}

        # --- 1. Check Essential Files ---
        cfg_file = project_path / 'scrapy.cfg'
        settings_file = project_path / project_name / 'settings.py'
        items_file = project_path / project_name / 'items.py'
        spiders_dir = project_path / project_name / 'spiders'
        init_py = spiders_dir / '__init__.py'

        if not cfg_file.exists():
            results['errors'].append({'message': "`scrapy.cfg` is missing.", 'details': "This file is essential for Scrapy to recognize the project."})
        if not settings_file.exists():
            results['errors'].append({'message': f"`{project_name}/settings.py` is missing.", 'details': "Project settings cannot be loaded.", 'file': str(settings_file)})
        if not items_file.exists():
            results['warnings'].append({'message': f"`{project_name}/items.py` is missing.", 'details': "Recommended for defining data structure.", 'file': str(items_file)})
        if not spiders_dir.is_dir():
            results['errors'].append({'message': f"`{project_name}/spiders/` directory is missing.", 'details': "No place to put spider files.", 'file': str(spiders_dir)})
        elif not init_py.exists():
             results['info'].append({'message': f"`spiders/__init__.py` is missing.", 'details': "While not strictly required for simple projects, it's standard practice for Python packages.", 'file': str(init_py)})

        # --- 2. Check settings.py Syntax ---
        if settings_file.exists():
            try:
                content = settings_file.read_text(encoding='utf-8')
                ast.parse(content) # Use AST for safer parsing than compile()
                results['info'].append({'message': "`settings.py` syntax is valid.", 'file': str(settings_file)})
            except SyntaxError as e:
                results['errors'].append({
                    'message': f"Syntax error in `settings.py` (line {e.lineno}).",
                    'details': f"{e.msg}\nNear: {e.text}",
                    'file': str(settings_file),
                    'line': e.lineno
                })
            except Exception as e:
                 results['errors'].append({
                    'message': f"Could not parse `settings.py`.",
                    'details': f"Error: {e}",
                    'file': str(settings_file)
                })

        # --- 3. Check Common Settings ---
        if 'content' in locals(): # Only if settings file was read
             if 'ROBOTSTXT_OBEY = True' not in content and 'ROBOTSTXT_OBEY = False' not in content:
                 results['info'].append({
                     'message': "`ROBOTSTXT_OBEY` setting not explicitly found.",
                     'details': "Scrapy defaults to True. Consider setting it explicitly.",
                     'file': str(settings_file)
                 })
             elif 'ROBOTSTXT_OBEY = False' in content:
                 results['warnings'].append({
                     'message': "`ROBOTSTXT_OBEY` is set to False.",
                     'details': "Ensure you have permission to ignore robots.txt rules for target sites.",
                     'file': str(settings_file)
                 })

             # Example: Check for default User-Agent
             if f'USER_AGENT = "{project_name}' not in content and 'USER_AGENT =' not in content:
                 results['info'].append({
                     'message': "Default User-Agent seems unchanged.",
                     'details': "Consider setting a custom User-Agent (e.g., 'MyCoolBot (+http://mycontact.info)') to be polite.",
                     'file': str(settings_file)
                 })

        # --- 4. Check Spiders Directory ---
        if spiders_dir.is_dir():
            try:
                spider_files = list(spiders_dir.glob("*.py"))
                non_init_spider_files = [f for f in spider_files if f.name != '__init__.py']
                if not non_init_spider_files:
                    results['warnings'].append({'message': "`spiders/` directory contains no spider (.py) files (excluding __init__.py).", 'file': str(spiders_dir)})
                else:
                     results['info'].append({'message': f"Found {len(non_init_spider_files)} potential spider file(s) in `spiders/`.", 'file': str(spiders_dir)})
                # Check for non-python files (might indicate clutter)
                other_files = [f for f in spiders_dir.iterdir() if f.is_file() and f.suffix != '.py' and f.suffix != '.pyc']
                if other_files:
                     results['info'].append({'message': f"Found non-Python files in `spiders/`: {[f.name for f in other_files]}", 'details': "These are usually not needed here.", 'file': str(spiders_dir)})
            except Exception as e:
                 results['warnings'].append({'message': f"Could not fully analyze `spiders/` directory.", 'details': f"Error: {e}", 'file': str(spiders_dir)})


        # --- 5. Check items.py for Item definitions ---
        if items_file.exists():
             try:
                 items_content = items_file.read_text(encoding='utf-8')
                 if 'class ' in items_content and 'scrapy.Item' in items_content:
                      # Basic check, could use AST for accuracy
                      results['info'].append({'message': "`items.py` seems to define Scrapy Item(s).", 'file': str(items_file)})
                 else:
                      results['warnings'].append({'message': "`items.py` exists but doesn't appear to define a `scrapy.Item` subclass.", 'details': "Defining Items helps structure your data.", 'file': str(items_file)})
             except Exception as e:
                  results['warnings'].append({'message': f"Could not analyze `items.py`.", 'details': f"Error: {e}", 'file': str(items_file)})

        logger.info(f"Health check complete for {project_name}. Errors: {len(results['errors'])}, Warnings: {len(results['warnings'])}, Info: {len(results['info'])}")
        return results

    def on_app_exit(self):
        """Placeholder for cleanup if needed."""
        logger.info(f"{self.name} plugin exiting.")