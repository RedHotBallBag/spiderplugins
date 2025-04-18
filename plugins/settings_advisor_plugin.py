import logging
import sys
import json
import os
import ast # Abstract Syntax Trees for safer parsing
import re
from pathlib import Path
import webbrowser # For opening docs

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QTreeWidget, QTreeWidgetItem, QPushButton,
                               QDialogButtonBox, QMessageBox, QSizePolicy,
                               QWidget)
from PySide6.QtCore import Qt, Slot, QUrl

# Import Plugin Base
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Helper for Tree Items ---
def create_advisor_tree_item(text, icon_name=None, tooltip=None, file_path=None, line_number=None, url=None):
    """Creates a QTreeWidgetItem with icon, tooltip, and associated data."""
    item = QTreeWidgetItem([text])
    if icon_name:
        icon = QIcon.fromTheme(icon_name)
        if not icon.isNull():
            item.setIcon(0, icon)
        else: # Fallback text prefix
            prefix_map = {"dialog-error": "[E]", "dialog-warning": "[W]", "dialog-information": "[I]", "preferences-system": "[R]"}
            prefix = prefix_map.get(icon_name, "[?]")
            item.setText(0, f"{prefix} {text}")

    item.setToolTip(0, tooltip if tooltip else text)
    item.setData(0, Qt.UserRole, file_path) # File path (str or None)
    item.setData(0, Qt.UserRole + 1, line_number) # Line number (int or None)
    item.setData(0, Qt.UserRole + 2, url) # Documentation URL (str or None)
    return item


# --- Settings Advisor Dialog ---
class SettingsAdvisorDialog(QDialog):
    """Dialog to display settings analysis results."""
    # Signal: file_path (str), line_number (int or None)
    open_file_requested = QtCore.Signal(str, object) # <--- CORRECT (use QtCore.Signal)

    def __init__(self, project_name, analysis_results, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Settings Analysis: {project_name}")
        self.setMinimumSize(700, 500)
        self.results = analysis_results
        self._init_ui()
        self.populate_results()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Summary Label
        self.summary_label = QLabel("Analysis Results:")
        self.summary_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.summary_label)

        # Results Tree
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabel("Setting Check / Recommendation")
        self.results_tree.setColumnCount(1)
        self.results_tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.results_tree)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def populate_results(self):
        """Fills the tree widget with check results."""
        self.results_tree.clear()

        warnings = self.results.get('warnings', [])
        recommendations = self.results.get('recommendations', [])
        info = self.results.get('info', [])

        # --- Create Top-Level Categories ---
        warn_item = QTreeWidgetItem(self.results_tree, ["Warnings"])
        warn_item.setIcon(0, QIcon.fromTheme("dialog-warning"))
        warn_item.setExpanded(len(warnings) > 0)
        warn_item.setHidden(len(warnings) == 0)

        rec_item = QTreeWidgetItem(self.results_tree, ["Recommendations"])
        rec_item.setIcon(0, QIcon.fromTheme("preferences-system")) # Suggestion icon
        rec_item.setExpanded(len(recommendations) > 0)
        rec_item.setHidden(len(recommendations) == 0)

        info_item = QTreeWidgetItem(self.results_tree, ["Information"])
        info_item.setIcon(0, QIcon.fromTheme("dialog-information"))
        info_item.setExpanded(len(warnings) == 0 and len(recommendations) == 0) # Expand if only info
        info_item.setHidden(len(info) == 0)

        # --- Populate Items ---
        for item_data in warnings:
            warn_item.addChild(create_advisor_tree_item(
                item_data['message'],
                icon_name="emblem-important",
                tooltip=item_data.get('details'),
                file_path=item_data.get('file'),
                line_number=item_data.get('line'),
                url=item_data.get('url')
            ))

        for item_data in recommendations:
            rec_item.addChild(create_advisor_tree_item(
                item_data['message'],
                icon_name="help-hint",
                tooltip=item_data.get('details'),
                file_path=item_data.get('file'),
                line_number=item_data.get('line'),
                url=item_data.get('url')
            ))

        for item_data in info:
            info_item.addChild(create_advisor_tree_item(
                item_data['message'],
                icon_name="edit-find", # Info/search icon
                tooltip=item_data.get('details'),
                file_path=item_data.get('file'),
                line_number=item_data.get('line'),
                url=item_data.get('url')
            ))

        self.results_tree.resizeColumnToContents(0)

    @Slot(QTreeWidgetItem, int)
    def _on_item_double_clicked(self, item, column):
        """Emits signal to open file or URL when an item is double-clicked."""
        file_path = item.data(0, Qt.UserRole)
        line_number = item.data(0, Qt.UserRole + 1)
        url = item.data(0, Qt.UserRole + 2)

        if file_path:
            logger.info(f"Requesting to open file: {file_path} at line {line_number}")
            self.open_file_requested.emit(str(file_path), line_number)
        elif url:
            logger.info(f"Opening documentation URL: {url}")
            if not QDesktopServices.openUrl(QUrl(url)):
                 logger.warning(f"Could not open URL: {url}")
                 QMessageBox.warning(self, "Cannot Open URL", f"Could not open the documentation link:\n{url}")


# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Scrapy Settings Advisor Plugin.
    """
    def __init__(self):
        super().__init__()
        self.name = "Settings Advisor"
        self.description = "Analyzes project settings.py for best practices and potential issues."
        self.version = "1.0.0"
        self.main_window = None

    def initialize_ui(self, main_window):
        """Add menu item to trigger the settings advisor dialog."""
        self.main_window = main_window

        if not hasattr(main_window, 'menuBar') or not hasattr(main_window, 'project_controller'):
            logger.error(f"{self.name}: Required MainWindow components (menuBar, project_controller) not found. Plugin disabled.")
            return

        menubar = main_window.menuBar()
        tools_menu_action = None
        for action in menubar.actions():
            if action.menu() and action.text().strip().replace('&','').lower() == "tools":
                tools_menu_action = action
                break

        if not tools_menu_action:
             tools_menu = menubar.addMenu("&Tools")
        else:
             tools_menu = tools_menu_action.menu()

        if not tools_menu:
             logger.error(f"{self.name}: Failed to get or create Tools menu.")
             return

        analyze_action = QAction(QIcon.fromTheme("preferences-system", QIcon.fromTheme("document-properties")), # Settings/Prefs icon
                                "Analyze Project Settings...", main_window)
        analyze_action.setToolTip("Check settings.py for recommendations and warnings.")
        analyze_action.triggered.connect(self._show_advisor_dialog)
        tools_menu.addAction(analyze_action)

        logger.info(f"{self.name} plugin initialized UI.")


    @Slot()
    def _show_advisor_dialog(self):
        """Gets the current project and shows the advisor dialog."""
        if not self.main_window or not hasattr(self.main_window, 'current_project') or not self.main_window.current_project:
            QMessageBox.warning(self.main_window, "No Project", "Please select a project first.")
            return

        project_data = self.main_window.current_project
        project_path = Path(project_data.get('path', ''))
        project_name = project_data.get('name', 'Unknown Project')

        if not project_path or not project_path.is_dir():
            QMessageBox.critical(self.main_window, "Error", f"Invalid path for project '{project_name}'.")
            return

        settings_file = project_path / project_name / 'settings.py'
        if not settings_file.exists():
             QMessageBox.warning(self.main_window, "File Not Found", f"Could not find settings file:\n{settings_file}")
             return

        # Run analysis
        try:
            QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
            results = self._analyze_settings(settings_file, project_name)
        except Exception as e:
             logger.exception(f"Error analyzing settings for project {project_name}:")
             QMessageBox.critical(self.main_window, "Analysis Failed", f"An error occurred during settings analysis:\n{e}")
             return
        finally:
             QtWidgets.QApplication.restoreOverrideCursor()

        # Show dialog
        dialog = SettingsAdvisorDialog(project_name, results, self.main_window)
        if hasattr(self.main_window, '_open_file'):
             dialog.open_file_requested.connect(self._request_open_file_line)
        else:
             logger.warning("Main window lacks '_open_file'. Double-click navigation disabled.")
        dialog.exec()


    @Slot(str, object) # file_path (str), line_number (int or None)
    def _request_open_file_line(self, file_path, line_number):
         """Handles request to open file and potentially go to line."""
         if self.main_window._open_file(file_path): # If file opens successfully
              if line_number is not None and hasattr(self.main_window, 'code_editor'):
                   try:
                       editor = self.main_window.code_editor
                       cursor = editor.textCursor()
                       cursor.movePosition(QtGui.QTextCursor.Start)
                       cursor.movePosition(QtGui.QTextCursor.Down, QtGui.QTextCursor.MoveAnchor, line_number - 1)
                       cursor.movePosition(QtGui.QTextCursor.StartOfLine, QtGui.QTextCursor.MoveAnchor) # Go to start of line
                       editor.setTextCursor(cursor)
                       editor.ensureCursorVisible()
                       logger.info(f"Moved editor cursor to line {line_number} in {Path(file_path).name}")
                   except Exception as e:
                       logger.warning(f"Could not move cursor to line {line_number}: {e}")


    def _analyze_settings(self, settings_path: Path, project_name: str):
        """Analyzes the settings.py file."""
        logger.info(f"Analyzing settings file: {settings_path}")
        results = {'warnings': [], 'recommendations': [], 'info': []}
        content = ""
        tree = None
        settings_found = {} # Store found setting assignments: {name: {'value': node, 'line': int}}

        # 1. Read and Parse
        try:
            content = settings_path.read_text(encoding='utf-8')
            tree = ast.parse(content, filename=str(settings_path))
            results['info'].append({
                'message': "Syntax check passed.",
                'file': str(settings_path)
            })
        except SyntaxError as e:
            results['warnings'].append({ # Treat syntax error as warning allowing other checks
                'message': f"Syntax error (line {e.lineno}): {e.msg}",
                'details': f"Near: {e.text}",
                'file': str(settings_path), 'line': e.lineno
            })
            # Cannot reliably parse further with AST if syntax is broken
            # Fall back to regex/string search for some key settings
            # (Implementation below handles this by checking if 'tree' is None)
        except Exception as e:
            results['warnings'].append({
                'message': f"Could not read or parse settings file.",
                'details': f"Error: {e}", 'file': str(settings_path)
            })
            # Cannot proceed if file unreadable
            return results

        # 2. Extract Setting Assignments (using AST if possible)
        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                            setting_name = target.id
                            # Store the value node and line number
                            settings_found[setting_name] = {'value_node': node.value, 'line': node.lineno}

        # --- 3. Perform Specific Checks ---
        # Note: These checks use the 'settings_found' dict (from AST) or fallback to regex on 'content'

        # ROBOTSTXT_OBEY
        doc_url = "https://docs.scrapy.org/en/latest/topics/settings.html#robotstxt-obey"
        robot_setting = settings_found.get('ROBOTSTXT_OBEY')
        if robot_setting:
            value = self._get_node_value(robot_setting['value_node'])
            if value is False:
                results['warnings'].append({
                    'message': "`ROBOTSTXT_OBEY` is set to False.",
                    'details': "Ensure you have permission and understand the implications of ignoring robots.txt.",
                    'file': str(settings_path), 'line': robot_setting['line'], 'url': doc_url
                })
            else:
                 results['info'].append({'message': "`ROBOTSTXT_OBEY` is explicitly set (likely True).", 'file': str(settings_path), 'line': robot_setting['line'], 'url': doc_url})
        elif not re.search(r"^\s*ROBOTSTXT_OBEY\s*=", content, re.MULTILINE): # Check if commented out or missing
            results['info'].append({'message': "`ROBOTSTXT_OBEY` is not explicitly set (defaults to True).", 'details': "Scrapy respects robots.txt by default.", 'file': str(settings_path), 'url': doc_url})

        # USER_AGENT
        doc_url = "https://docs.scrapy.org/en/latest/topics/settings.html#user-agent"
        ua_setting = settings_found.get('USER_AGENT')
        default_ua_pattern = rf'^\s*#?\s*USER_AGENT\s*=\s*[\'"]{project_name}' # Checks commented or active default
        custom_ua_pattern = r'^\s*USER_AGENT\s*=\s*[^#]' # Active, non-commented USER_AGENT line

        if ua_setting:
             value = self._get_node_value(ua_setting['value_node'])
             if isinstance(value, str) and project_name in value: # Simple check for default
                 results['recommendations'].append({
                    'message': "Default `USER_AGENT` is likely used.",
                    'details': "Set a custom User-Agent identifying your bot (e.g., 'MyBot (+http://mywebsite.com)') for politeness.",
                    'file': str(settings_path), 'line': ua_setting['line'], 'url': doc_url
                 })
             else:
                  results['info'].append({'message': "Custom `USER_AGENT` seems to be set.", 'file': str(settings_path), 'line': ua_setting['line'], 'url': doc_url})
        elif re.search(default_ua_pattern, content, re.MULTILINE) or not re.search(custom_ua_pattern, content, re.MULTILINE):
             results['recommendations'].append({
                'message': "`USER_AGENT` is likely commented out or missing.",
                'details': "Set a custom User-Agent identifying your bot (e.g., 'MyBot (+http://mywebsite.com)') for politeness.",
                'file': str(settings_path), 'url': doc_url # No specific line number from regex
             })

        # DOWNLOAD_DELAY & CONCURRENT_REQUESTS*
        doc_url_delay = "https://docs.scrapy.org/en/latest/topics/settings.html#download-delay"
        doc_url_conc = "https://docs.scrapy.org/en/latest/topics/settings.html#concurrent-requests-per-domain"
        delay_setting = settings_found.get('DOWNLOAD_DELAY')
        conc_domain_setting = settings_found.get('CONCURRENT_REQUESTS_PER_DOMAIN')
        conc_ip_setting = settings_found.get('CONCURRENT_REQUESTS_PER_IP')
        autothrottle_setting = settings_found.get('AUTOTHROTTLE_ENABLED')
        autothrottle_enabled = autothrottle_setting and self._get_node_value(autothrottle_setting['value_node']) is True

        delay_value = self._get_node_value(delay_setting['value_node']) if delay_setting else 0
        conc_domain_value = self._get_node_value(conc_domain_setting['value_node']) if conc_domain_setting else 16 # Scrapy default
        conc_ip_value = self._get_node_value(conc_ip_setting['value_node']) if conc_ip_setting else 16 # Scrapy default

        if not autothrottle_enabled:
            if delay_value is None or delay_value < 0.5: # Check if explicitly set to a low value or unset
                 results['recommendations'].append({
                     'message': "Low/No `DOWNLOAD_DELAY` without AutoThrottle.",
                     'details': f"Consider setting DOWNLOAD_DELAY >= 0.5 or enabling AUTOTHROTTLE_ENABLED for politeness. Current delay appears to be {delay_value if delay_value is not None else 'default (0)'}.",
                     'file': str(settings_path), 'line': delay_setting['line'] if delay_setting else None, 'url': doc_url_delay
                 })
            if conc_domain_value > 8 or conc_ip_value > 8:
                 results['recommendations'].append({
                     'message': "High concurrency without AutoThrottle.",
                     'details': f"Consider lowering CONCURRENT_REQUESTS_PER_DOMAIN/IP (currently ~{conc_domain_value}/{conc_ip_value}) or enabling AUTOTHROTTLE_ENABLED to avoid overloading servers.",
                     'file': str(settings_path), 'line': (conc_domain_setting or conc_ip_setting)['line'] if (conc_domain_setting or conc_ip_setting) else None, 'url': doc_url_conc
                 })
        else:
            results['info'].append({'message': "`AUTOTHROTTLE_ENABLED` is True.", 'details': "AutoThrottle adjusts delays/concurrency automatically.", 'file': str(settings_path), 'line': autothrottle_setting['line'] if autothrottle_setting else None, 'url': 'https://docs.scrapy.org/en/latest/topics/autothrottle.html'})

        # HTTPCACHE_ENABLED
        doc_url = "https://docs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings"
        cache_setting = settings_found.get('HTTPCACHE_ENABLED')
        if not cache_setting or self._get_node_value(cache_setting['value_node']) is False:
            results['recommendations'].append({
                'message': "HTTP Caching is disabled.",
                'details': "Enable `HTTPCACHE_ENABLED = True` during development to speed up repeated crawls by caching requests.",
                'file': str(settings_path), 'line': cache_setting['line'] if cache_setting else None, 'url': doc_url
            })
        else:
             results['info'].append({'message': "`HTTPCACHE_ENABLED` is True.", 'details': "Caching requests can speed up development.", 'file': str(settings_path), 'line': cache_setting['line'], 'url': doc_url})

        # Check for common extensions
        # These checks remain regex/string based as they often involve complex dicts/lists
        if 'scrapy_playwright' in content:
             results['info'].append({'message': "Playwright integration detected.", 'details': "Ensure DOWNLOAD_HANDLERS and TWISTED_REACTOR are set correctly.", 'file': str(settings_path)})
        if 'scrapy_splash' in content:
             results['info'].append({'message': "Splash integration detected.", 'details': "Ensure SPLASH_URL and relevant middlewares are configured.", 'file': str(settings_path)})
        if 'scrapy_redis' in content:
             results['info'].append({'message': "Scrapy-Redis integration detected.", 'details': "Ensure SCHEDULER, DUPEFILTER_CLASS, and Redis connection settings are correct.", 'file': str(settings_path)})


        logger.info(f"Settings analysis complete for {settings_path.name}.")
        return results

    def _get_node_value(self, node):
        """Safely evaluate simple literal values from AST nodes."""
        if node is None:
            return None
        try:
            # Use literal_eval for safety, handles basic types
            return ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            # Fallback for more complex expressions or non-literals
            # Could try to reconstruct string, but risky. Return None for now.
            logger.debug(f"Could not literal_eval node: {ast.dump(node)}")
            return None


    def on_app_exit(self):
        """Placeholder for cleanup if needed."""
        logger.info(f"{self.name} plugin exiting.")