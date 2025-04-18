# plugins/spider_hub_plugin.py
import logging
import sys
import json
import os
import threading
import re
import functools # Import functools
from pathlib import Path
import webbrowser

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QColor, QDesktopServices, QSyntaxHighlighter, QFontDatabase # Added QFontDatabase
from PySide6.QtWidgets import (QMessageBox, QApplication, QDialog, QTableWidgetItem,
                               QTextBrowser, QPlainTextEdit, QProgressDialog, QGroupBox,
                               QVBoxLayout, QFormLayout, QLabel, QHBoxLayout, QPushButton,
                               QListWidget, QListWidgetItem, QSplitter, QLineEdit,
                               QComboBox, QTableWidget, QHeaderView, QDialogButtonBox) # More specific imports
from PySide6.QtCore import Qt, Slot, Signal, QObject, QThread, QUrl

# Import Plugin Base
from app.plugin_base import PluginBase
try:
    from app.editor.code_editor import PythonHighlighter
    HIGHLIGHTER_AVAILABLE = True
except ImportError:
    HIGHLIGHTER_AVAILABLE = False
    logging.warning("Spider Hub: PythonHighlighter not found in editor. Code view will not be highlighted.")


# --- Dependency Checks ---
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.warning("Spider Hub Plugin: 'requests' library not found. Please install it (`pip install requests`). Network features will be disabled.")

try:
    from packaging.version import parse as parse_version, InvalidVersion
    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False
    logging.warning("Spider Hub Plugin: 'packaging' library not found (`pip install packaging`). Version comparison will be basic string comparison.")

logger = logging.getLogger(__name__)

# --- Configuration ---
DEFAULT_SPIDERS_CATALOG_URL = "https://raw.githubusercontent.com/RedHotBallBag/spiderplugins/refs/heads/main/spiders_catalog.json"

# --- Network Worker (Remains the same) ---
class NetworkWorker(QObject):
    catalog_fetched = Signal(list)
    # download_finished: success(bool), id(str, filename_hint), content(str), target_path(Path, optional), project_name(str, optional)
    download_finished = Signal(bool, str, str, object, object) # Use object for Path/None flexibility
    error_occurred = Signal(str)
    status_update = Signal(str) # Signal for intermediate status updates

    def __init__(self, catalog_url_or_path):
        super().__init__()
        self.source = catalog_url_or_path
        self.is_url = str(self.source).lower().startswith(('http://', 'https://'))

    @Slot()
    def fetch_catalog(self):
        self.status_update.emit("Fetching catalog list...")
        catalog_data = [] # Initialize catalog_data before try block
        try:
            if self.is_url:
                if not REQUESTS_AVAILABLE:
                    self.error_occurred.emit("Network library ('requests') is missing.")
                    return
                logger.info(f"Fetching spider catalog from URL: {self.source}")
                response = requests.get(self.source, timeout=15)
                response.raise_for_status()
                catalog_data = response.json() # Assign here on success
            else: # Local file path
                logger.info(f"Loading spider catalog from local file: {self.source}")
                local_path = Path(self.source)
                if not local_path.exists():
                     raise FileNotFoundError(f"Catalog file not found: {self.source}")
                with open(local_path, 'r', encoding='utf-8') as f:
                    catalog_data = json.load(f) # Assign here on success

            if not isinstance(catalog_data, list):
                raise ValueError("Catalog format is invalid (expected a JSON list).")
            logger.info(f"Successfully loaded {len(catalog_data)} entries from catalog.")
            self.catalog_fetched.emit(catalog_data)
            self.status_update.emit(f"Catalog loaded ({len(catalog_data)} entries).")

        except FileNotFoundError as e:
             logger.error(f"Error loading local catalog file: {e}")
             self.error_occurred.emit(f"File Not Found: {e}")
             self.status_update.emit("Catalog loading failed.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching catalog URL: {e}")
            self.error_occurred.emit(f"Network Error: {e}")
            self.status_update.emit("Catalog loading failed (Network).")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding catalog JSON: {e}")
            self.error_occurred.emit(f"Catalog Format Error: {e}")
            self.status_update.emit("Catalog loading failed (Format).")
        except ValueError as e:
             logger.error(f"Catalog validation error: {e}")
             self.error_occurred.emit(f"Catalog Error: {e}")
             self.status_update.emit("Catalog loading failed (Validation).")
        except Exception as e:
            logger.exception("Unexpected error fetching/loading catalog:")
            self.error_occurred.emit(f"Unexpected Error: {e}")
            self.status_update.emit("Catalog loading failed (Unexpected).")

    @Slot(str, str, object, object) # download_url, filename_hint, target_path=None, project_name=None
    def download_file_content(self, download_url, filename_hint, target_path=None, project_name=None):
        if not self.is_url or not REQUESTS_AVAILABLE: # Only download from URL here
            err_msg = "Cannot download: Source is local or 'requests' library is missing."
            self.error_occurred.emit(err_msg)
            self.download_finished.emit(False, filename_hint, "", target_path, project_name)
            self.status_update.emit("Download failed (Setup Error).")
            return

        self.status_update.emit(f"Downloading {filename_hint}...")
        content = ""
        success = False
        try:
            logger.info(f"Downloading content for '{filename_hint}' from: {download_url}")
            response = requests.get(download_url, timeout=30)
            response.raise_for_status()
            content = response.text
            success = True
            logger.info(f"Successfully downloaded content for '{filename_hint}' ({len(content)} bytes).")
            self.status_update.emit(f"Download complete: {filename_hint}.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error downloading content {filename_hint}: {e}")
            err_msg = f"Download Error for {filename_hint}: {e}"
            self.error_occurred.emit(err_msg)
            self.status_update.emit(f"Download failed: {filename_hint}.")
        except Exception as e:
            logger.exception(f"Unexpected error downloading content {filename_hint}:")
            err_msg = f"Download Error for {filename_hint}: {e}"
            self.error_occurred.emit(err_msg)
            self.status_update.emit(f"Download failed: {filename_hint}.")
        finally:
            # Emit finished signal regardless of success, passing context back
            self.download_finished.emit(success, filename_hint, content, target_path, project_name)


# --- Code Viewer Dialog (remains the same) ---
class CodeViewerDialog(QtWidgets.QDialog):
    def __init__(self, title, code_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Code Viewer - {title}")
        self.setMinimumSize(700, 550)

        layout = QtWidgets.QVBoxLayout(self)
        self.code_browser = QtWidgets.QPlainTextEdit()
        self.code_browser.setReadOnly(True)
        self.code_browser.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        fixed_font.setPointSize(10)
        self.code_browser.setFont(fixed_font)
        self.code_browser.setPlainText(code_content)

        if HIGHLIGHTER_AVAILABLE:
             try:
                 self.highlighter = PythonHighlighter(self.code_browser.document())
             except Exception as high_e:
                  logger.error(f"Failed to apply PythonHighlighter: {high_e}")

        layout.addWidget(self.code_browser)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


# --- Spider Hub Dialog ---
class SpiderHubDialog(QtWidgets.QDialog):
    # (... __init__, _init_ui, _get_installed_plugins, _get_local_plugin_version ...)
    # (... _refresh_catalog, _catalog_loaded, _handle_load_error, _filter_table ...)
    # (... _on_selection_changed, _clear_details_panel ...)
    # (... _view_code, _show_code_dialog, _handle_code_download_error ...)
    def __init__(self, catalog_source, project_controller, parent=None):
        super().__init__(parent)
        self.catalog_source = catalog_source # URL or Path
        self.project_controller = project_controller # Reference to main controller
        self.parent_window = parent # Reference to main window
        self.catalog_data = [] # All loaded spider infos
        self.filtered_catalog_data = [] # Data currently displayed
        self.worker = None
        self.thread = None
        self.current_code_cache = {} # Cache code content {filename: content}

        self.setWindowTitle("Spider Hub - Discover & Add Spiders")
        self.setMinimumSize(850, 650)

        self._init_ui()
        self._refresh_catalog() # Fetch on open

    def _init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(10)

        # --- Top Controls ---
        controls_layout = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search by name, website, tag, description...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_table)

        refresh_button = QtWidgets.QPushButton("Refresh Catalog")
        refresh_button.setIcon(QIcon.fromTheme("view-refresh"))
        refresh_button.clicked.connect(self._refresh_catalog)

        controls_layout.addWidget(QtWidgets.QLabel("Filter:"))
        controls_layout.addWidget(self.search_input)
        controls_layout.addWidget(refresh_button)
        main_layout.addLayout(controls_layout)

        # --- Main Splitter ---
        splitter = QtWidgets.QSplitter(Qt.Vertical)

        # Table View (Top Pane)
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(5) # Name, Targets, Author, Version, Tags
        self.table.setHorizontalHeaderLabels(["Name", "Target Websites", "Author", "Version", "Tags"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True) # Stretch last column (Tags)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents) # Name
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch) # Targets
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents) # Author
        self.table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents) # Version
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        # Details View (Bottom Pane)
        details_widget = QtWidgets.QWidget()
        details_layout = QtWidgets.QVBoxLayout(details_widget)
        details_layout.setContentsMargins(5,5,5,5)

        details_group = QGroupBox("Selected Spider Details")
        details_form = QFormLayout(details_group)
        details_form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        self.details_name_label = QLabel("<i>Select a spider above</i>")
        self.details_desc_browser = QTextBrowser() # Use browser for potential links/formatting
        self.details_desc_browser.setOpenExternalLinks(True)
        self.details_desc_browser.setMaximumHeight(100) # Limit height
        self.details_deps_label = QLabel("<i>N/A</i>")
        self.details_notes_browser = QTextBrowser()
        self.details_notes_browser.setOpenExternalLinks(True)
        self.details_notes_browser.setMaximumHeight(80)

        details_form.addRow("<b>Name:</b>", self.details_name_label)
        details_form.addRow("<b>Description:</b>", self.details_desc_browser)
        details_form.addRow("<b>Dependencies:</b>", self.details_deps_label)
        details_form.addRow("<b>Notes:</b>", self.details_notes_browser)

        details_layout.addWidget(details_group)

        # Action Buttons for Details Panel
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        self.view_code_button = QPushButton("View Code")
        self.view_code_button.setIcon(QIcon.fromTheme("document-edit-symbolic", QIcon.fromTheme("text-x-script")))
        self.view_code_button.setEnabled(False)
        self.view_code_button.clicked.connect(self._view_code)

        self.add_to_project_button = QPushButton("Add to Project...")
        self.add_to_project_button.setIcon(QIcon.fromTheme("list-add", QIcon.fromTheme("document-save-as")))
        self.add_to_project_button.setEnabled(False)
        self.add_to_project_button.clicked.connect(self._add_to_project)

        action_layout.addWidget(self.view_code_button)
        action_layout.addWidget(self.add_to_project_button)
        details_layout.addLayout(action_layout)

        splitter.addWidget(details_widget)
        main_layout.addWidget(splitter)
        splitter.setSizes([400, 250]) # Adjust initial split

        # Status Label
        self.status_label = QLabel(" ") # Start with blank status
        main_layout.addWidget(self.status_label)

        # Disable table initially
        self.table.setEnabled(False)

    def _get_installed_plugins(self):
        # This function name is misleading in this context, it should be
        # checking for installed *spiders* if we wanted to compare,
        # but the current logic doesn't use it, so we keep it simple.
        # We might use it later for version comparison if spiders have versions.
        return set() # Return empty set for now

    def _get_local_plugin_version(self, filename):
        # ... (same as before) ...
        if not PACKAGING_AVAILABLE: return None
        local_path = self.plugins_dir / filename # This path might be wrong for spiders
        if not local_path.exists(): return None
        try:
            content = local_path.read_text(encoding='utf-8', errors='ignore')
            match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
            if match:
                version_str = match.group(1)
                try:
                    parse_version(version_str)
                    return version_str
                except InvalidVersion: return None
            else: return None
        except Exception: return None


    @Slot()
    def _refresh_catalog(self):
        """Initiates fetching/loading the catalog in a thread."""
        # --- Setup Worker and Thread ---
        if self.thread and self.thread.isRunning():
            logger.warning("Catalog fetch already in progress.")
            return
        self.status_label.setText("Loading catalog...")
        self.table.setEnabled(False)
        self.table.setRowCount(0)
        self._clear_details_panel()

        self.thread = QThread(self)
        # Pass the source (URL or path) from self.catalog_source
        self.worker = NetworkWorker(self.catalog_source)
        self.worker.moveToThread(self.thread)

        # --- Connect Signals ---
        self.worker.catalog_fetched.connect(self._catalog_loaded)
        self.worker.error_occurred.connect(self._handle_load_error)
        self.worker.status_update.connect(self._update_status_label) # Connect status updates
        self.thread.started.connect(self.worker.fetch_catalog)
        # Cleanup connections
        self.worker.catalog_fetched.connect(self.thread.quit)
        self.worker.error_occurred.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: setattr(self, 'thread', None))
        self.thread.finished.connect(lambda: setattr(self, 'worker', None))

        self.thread.start()

    @Slot(list)
    def _catalog_loaded(self, catalog_data):
        """Callback when catalog data is fetched/loaded successfully."""
        self.catalog_data = catalog_data
        self._filter_table() # Populate table via filter function
        self.table.setEnabled(True)
        # Status updated by worker signal

    @Slot(str)
    def _handle_load_error(self, error_message):
        """Displays catalog loading errors."""
        self._update_status_label(f"<font color='red'>Error loading catalog: {error_message}</font>")
        self.table.setEnabled(False)
        self.catalog_data = []
        self.filtered_catalog_data = []
        self.table.setRowCount(0)
        self._clear_details_panel()
        QMessageBox.warning(self, "Catalog Load Error", f"Could not load spider catalog:\n{error_message}")

    @Slot()
    def _filter_table(self):
        """Filters table based on search input and populates it."""
        search_term = self.search_input.text().lower().strip()
        self.table.setRowCount(0) # Clear table first
        self.filtered_catalog_data = [] # Reset filtered list

        if not self.catalog_data:
            return

        # Filter data
        if not search_term:
            self.filtered_catalog_data = self.catalog_data
        else:
            for spider_info in self.catalog_data:
                match = False
                if search_term in spider_info.get("name", "").lower(): match = True
                if not match and search_term in spider_info.get("description", "").lower(): match = True
                if not match and search_term in spider_info.get("author", "").lower(): match = True
                if not match and any(search_term in site.lower() for site in spider_info.get("target_websites", [])): match = True
                if not match and any(search_term in tag.lower() for tag in spider_info.get("tags", [])): match = True
                if match: self.filtered_catalog_data.append(spider_info)

        # Populate table with filtered data
        self.table.setRowCount(len(self.filtered_catalog_data))
        for row, spider_info in enumerate(self.filtered_catalog_data):
            name_item = QTableWidgetItem(spider_info.get("name", "N/A"))
            name_item.setData(Qt.UserRole, spider_info)
            name_item.setToolTip(spider_info.get("description", ""))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(", ".join(spider_info.get("target_websites", []))))
            self.table.setItem(row, 2, QTableWidgetItem(spider_info.get("author", "N/A")))
            self.table.setItem(row, 3, QTableWidgetItem(spider_info.get("version", "N/A")))
            self.table.setItem(row, 4, QTableWidgetItem(", ".join(spider_info.get("tags", []))))

        self.table.resizeRowsToContents()
        status_msg = f"Showing {len(self.filtered_catalog_data)} spiders."
        if not self.filtered_catalog_data and search_term:
             status_msg = "No spiders match filter."
        self._update_status_label(status_msg)

        self._clear_details_panel() # Clear details panel when filtering changes


    @Slot()
    def _on_selection_changed(self):
        """Updates the details panel when table selection changes."""
        selected_items = self.table.selectedItems()
        if not selected_items:
            self._clear_details_panel()
            return

        selected_row = selected_items[0].row()
        first_item = self.table.item(selected_row, 0)
        spider_info = first_item.data(Qt.UserRole) if first_item else None

        if not spider_info:
             self._clear_details_panel()
             return

        self.details_name_label.setText(f"<b>{spider_info.get('name', 'N/A')}</b> (v{spider_info.get('version', '?')})")
        self.details_desc_browser.setText(spider_info.get('description', 'N/A'))
        self.details_deps_label.setText(", ".join(spider_info.get('dependencies', [])) or "<i>None listed</i>")
        self.details_notes_browser.setText(spider_info.get('notes', '<i>None</i>'))

        can_download = bool(spider_info.get("download_url"))
        self.view_code_button.setEnabled(can_download)
        self.add_to_project_button.setEnabled(can_download)

        # Clear code cache when selection changes
        self.current_code_cache = {}


    def _clear_details_panel(self):
         """Resets the detail labels and buttons."""
         self.details_name_label.setText("<i>Select a spider above</i>")
         self.details_desc_browser.clear()
         self.details_desc_browser.setPlaceholderText("Select a spider to see details.")
         self.details_deps_label.setText("<i>N/A</i>")
         self.details_notes_browser.clear()
         self.details_notes_browser.setPlaceholderText("")
         self.view_code_button.setEnabled(False)
         self.add_to_project_button.setEnabled(False)
         self.current_code_cache = {}

    @Slot()
    def _view_code(self):
        """Fetches and shows the spider code in a dialog."""
        selected_items = self.table.selectedItems()
        if not selected_items: return
        spider_info = self.table.item(selected_items[0].row(), 0).data(Qt.UserRole)
        if not spider_info: return

        download_url = spider_info.get("download_url")
        filename = spider_info.get("filename", "unknown_spider.py")
        title = spider_info.get("name", "Unknown Spider")

        if not download_url:
            QMessageBox.warning(self, "Missing URL", "No download URL specified for this spider.")
            return

        # --- Use cached code if available ---
        if filename in self.current_code_cache:
            logger.debug(f"Using cached code for {filename}")
            dialog = CodeViewerDialog(title, self.current_code_cache[filename], self)
            dialog.exec()
            return

        # --- Fetch code in thread ---
        self.view_code_button.setEnabled(False)
        QApplication.processEvents()

        self.thread = QThread(self)
        self.worker = NetworkWorker(self.catalog_source)
        self.worker.moveToThread(self.thread)

        # --- Connect directly to the show code slot --- NO LONGER USING PARTIAL ---
        self.worker.download_finished.connect(self._show_code_dialog)

        self.worker.error_occurred.connect(self._handle_code_download_error)
        self.worker.status_update.connect(self._update_status_label)
        # Pass None for context args not relevant to download_file_content
        self.thread.started.connect(lambda: self.worker.download_file_content(download_url, filename, None, None))
        # Cleanup connections specific to this operation
        self.worker.error_occurred.connect(self.thread.quit) # Quit on error is okay
        # Worker deletion, button re-enabling, and reference clearing are handled by _finalize_view_operation
        # called from _show_code_dialog and _handle_code_download_error.
        # Keep worker deletion on thread finish as a fallback.
        self.thread.finished.connect(self.worker.deleteLater)

        self.thread.start()

    def _finalize_view_operation(self):
        """Cleans up resources and re-enables button after view code operation attempt."""
        logger.debug("[Spider Hub] Finalizing view code operation.")
        # Worker might already be scheduled for deletion by thread.finished, but doesn't hurt to clear ref
        self.worker = None
        # Thread might be finishing, clear ref
        self.thread = None
        # Re-enable button safely
        self.view_code_button.setEnabled(True)
        logger.debug("[Spider Hub] View code operation finalized.")

    # --- Slot signature now matches download_finished signal ---
    @Slot(bool, str, str, object, object) # success, filename_hint, content, target_path, project_name
    def _show_code_dialog(self, success, filename_hint, content, target_path, project_name):
        """Shows the downloaded code in the viewer dialog. Receives args directly from signal."""
        # Note: target_path and project_name are ignored here but received from the signal
        logger.debug(f"_show_code_dialog called. Success: {success}, Filename Hint (signal): {filename_hint}")

        if not success:
            logger.warning(f"Ignoring _show_code_dialog call (success=False) for hint: {filename_hint}")
            # Error handled by _handle_code_download_error, which calls finalize
            return

        # Check if this result still corresponds to the *currently selected* spider
        selected_items = self.table.selectedItems()
        current_filename = None
        if selected_items:
            current_spider_info = self.table.item(selected_items[0].row(), 0).data(Qt.UserRole)
            if current_spider_info:
                current_filename = current_spider_info.get("filename")

        if filename_hint != current_filename:
            logger.debug(f"Ignoring code download result for '{filename_hint}' as selection changed to '{current_filename}'.")
            # Finalize here as well, since we are ignoring the result
            self._finalize_view_operation()
            return

        logger.debug(f"Caching code content for {filename_hint}")
        self.current_code_cache[filename_hint] = content # Cache the content
        # Status update handled by worker

        # Use filename_hint for title consistency
        dialog = CodeViewerDialog(filename_hint, content, self)
        dialog.exec()
        # Finalize after the dialog is closed
        self._finalize_view_operation()

    @Slot(str)
    def _handle_code_download_error(self, error_message):
         self._update_status_label(f"<font color='red'>Error downloading code: {error_message}</font>")
         QMessageBox.warning(self, "Code Download Error", f"Could not download spider code:\n{error_message}")
         # Finalize after error
         self._finalize_view_operation()


    @Slot()
    def _add_to_project(self):
        """Downloads and saves the selected spider to a chosen project."""
        selected_items = self.table.selectedItems()
        if not selected_items:
             QMessageBox.warning(self, "No Selection", "Please select a spider from the table first.")
             return
        spider_info = self.table.item(selected_items[0].row(), 0).data(Qt.UserRole)
        if not spider_info: return

        download_url = spider_info.get("download_url")
        filename = spider_info.get("filename")
        spider_name_display = spider_info.get("name", "the selected spider")

        if not download_url or not filename:
            QMessageBox.critical(self, "Error", f"Missing download URL or filename for '{spider_name_display}'.")
            return

        projects_dict = self.project_controller.get_projects()
        if not projects_dict:
            QMessageBox.warning(self, "No Projects", "No projects found. Please add a project first.")
            return

        project_names = sorted(projects_dict.keys())
        project_name, ok = QtWidgets.QInputDialog.getItem(self, "Select Project", "Add spider to which project:", project_names, 0, editable=False)

        if not ok or not project_name: return

        project_data = projects_dict[project_name]
        outer_project_path = Path(project_data['path'])
        # Define the standard spiders directory path
        spiders_dir = outer_project_path / project_name / 'spiders'

        # Check if this standard directory exists
        if not spiders_dir.is_dir():
             # Ask to create the standard directory if it doesn't exist
             # Use relative_to for a cleaner message if possible, otherwise just the name
             try:
                 dir_display_name = spiders_dir.relative_to(outer_project_path)
             except ValueError:
                 dir_display_name = spiders_dir.name

             reply = QMessageBox.question(self, "Create Directory?",
                                          f"The standard spiders directory ({dir_display_name}) was not found in project '{project_name}'.\nCreate it now?",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
             if reply == QMessageBox.Yes:
                  try:
                       spiders_dir.mkdir(parents=True, exist_ok=True)
                       logger.info(f"Created missing spiders directory: {spiders_dir}")
                  except OSError as e:
                       QMessageBox.critical(self, "Error", f"Could not create spiders directory:\n{e}")
                       return
             else:
                  # User chose not to create the directory
                  logger.warning(f"User declined to create missing spiders directory: {spiders_dir}")
                  return # Exit if directory doesn't exist and wasn't created

        # Proceed using the standard spiders_dir path
        target_file_path = spiders_dir / filename
        logger.debug(f"Adding spider: {spider_name_display}")
        logger.debug(f"Download URL: {download_url}")
        logger.debug(f"Filename: {filename}")
        
        # Log project details
        logger.debug(f"Selected Project: {project_name}")
        logger.debug(f"Project Path: {outer_project_path}")
        logger.debug(f"Spiders Directory: {spiders_dir}")
        logger.debug(f"Target File Path: {target_file_path}")
        if target_file_path.exists():
            reply = QMessageBox.question(
                self, "File Exists",
                f"The file '{filename}' already exists in project '{project_name}'.\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.No: return

        # --- Download and Save (in thread) ---
        self.add_to_project_button.setEnabled(False)
        QApplication.processEvents()

        # --- Download and Save (in thread) --- NO LONGER USING PARTIAL ---
        self.thread = QThread(self)
        self.worker = NetworkWorker(self.catalog_source)
        self.worker.moveToThread(self.thread)

        # Connect directly to the save slot
        self.worker.download_finished.connect(self._save_downloaded_spider)
        self.worker.error_occurred.connect(self._handle_code_download_error) # Reuse error handler
        self.worker.status_update.connect(self._update_status_label) # Show progress
        # Pass target_file_path and project_name to the worker method
        # Pass target_file_path and project_name to the worker method
        self.thread.started.connect(lambda: self.worker.download_file_content(download_url, filename, target_file_path, project_name))
        # Cleanup - REMOVED self.worker.download_finished.connect(self.thread.quit)
        # Let the thread finish naturally after the slot executes
        self.worker.error_occurred.connect(self.thread.quit) # Quit on error
        # Worker deletion and button re-enabling will be handled explicitly in the slot or error handler now
        # self.thread.finished.connect(self.worker.deleteLater) # Now handled in slot/error handler
        # self.thread.finished.connect(lambda: setattr(self, 'thread', None)) # Now handled in slot/error handler
        # self.thread.finished.connect(lambda: setattr(self, 'worker', None)) # Now handled in slot/error handler
        # self.thread.finished.connect(lambda: self.add_to_project_button.setEnabled(True)) # Now handled in slot/error handler

        self.thread.start()

    def _finalize_add_operation(self):
        """Cleans up resources and re-enables button after add operation attempt."""
        logger.debug("[Spider Hub] Finalizing add operation.")
        if self.worker:
            # Ensure worker is deleted if not already scheduled
            self.worker.deleteLater()
            self.worker = None
        if self.thread:
            # Ensure thread is quit if still running and clear reference
            if self.thread.isRunning():
                self.thread.quit()
                # Optionally wait a short time, but might not be necessary
                # self.thread.wait(100)
            self.thread = None
        # Re-enable button safely
        self.add_to_project_button.setEnabled(True)
        logger.debug("[Spider Hub] Add operation finalized.")


    # --- Slot signature now matches download_finished signal ---
    @Slot(bool, str, str, object, object) # success, filename_hint, content, target_path, project_name
    def _save_downloaded_spider(self, success, filename_hint, content, target_path, project_name):
        """Saves the downloaded spider code to the target project. Receives args directly from signal."""
        logger.info(f"[Spider Hub] _save_downloaded_spider triggered for hint: {filename_hint}")
        logger.debug(f"Saving Spider Details (from signal):")
        logger.debug(f"  Success: {success}")
        logger.debug(f"  Filename Hint: {filename_hint}")
        logger.debug(f"  Content Length: {len(content) if content else 0}")
        logger.debug(f"  Target Path: {target_path}")
        logger.debug(f"  Project Name: {project_name}")

        # Ensure target_path is a Path object if it's not None
        if target_path and not isinstance(target_path, Path):
            logger.warning(f"[Spider Hub] Received target_path is not a Path object: {type(target_path)}. Attempting conversion.")
            try:
                target_path = Path(target_path)
            except Exception as e:
                logger.error(f"[Spider Hub] Failed to convert target_path to Path object: {e}")
                self._update_status_label(f"<font color='red'>Internal Error: Invalid save path.</font>")
                return

        # Check if target_path or project_name is None (shouldn't happen if called from _add_to_project)
        if target_path is None or project_name is None:
             logger.error(f"[Spider Hub] Save aborted: target_path or project_name is None. Hint: {filename_hint}")
             self._update_status_label(f"<font color='red'>Internal Error: Missing save context.</font>")
             return

        if not success:
            logger.warning(f"[Spider Hub] Download reported as failed (success=False) for '{filename_hint}'. Aborting save.")
            # Status update handled by worker/error handler
            return

        if not content.strip():
            logger.error(f"[Spider Hub] Downloaded spider content is empty for '{filename_hint}'.")
            QMessageBox.critical(self, "Error", f"The downloaded content for '{filename_hint}' is empty. Cannot save.")
            self._update_status_label(f"<font color='red'>Download failed: Empty content.</font>")
            return

        logger.info(f"[Spider Hub] Download successful for '{filename_hint}'. Proceeding to save.")
        try:
            logger.debug(f"[Spider Hub] Ensuring parent directory exists: {target_path.parent}")
            target_path.parent.mkdir(parents=True, exist_ok=True) # Ensure spiders dir exists
            logger.debug(f"[Spider Hub] Writing content ({len(content)} bytes) to: {target_path}")
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Spider '{filename_hint}' saved successfully to {target_path}")
            # Use project_name received from signal for the message
            self._update_status_label(f"Spider '{filename_hint}' added to project '{project_name}'.")
            QMessageBox.information(self, "Success",
                                    f"Spider '{filename_hint}' was added to project '{project_name}'.\n\n"
                                    "You may need to refresh the project's spider list or file tree in the main window.")
            # TODO: Ideally, emit a signal or call a method on main_window to refresh automatically

            # Finalize after success message
            self._finalize_add_operation()

        except OSError as e:
            logger.error(f"Error saving downloaded spider file {target_path}: {e}")
            QMessageBox.critical(self, "File Error", f"Could not save spider file to project:\n{e}")
            self._update_status_label(f"<font color='red'>Error saving {filename_hint}.</font>")
            # Finalize after error
            self._finalize_add_operation()
        except Exception as e:
             logger.exception(f"Unexpected error saving downloaded spider {filename_hint}:")
             QMessageBox.critical(self, "Error", f"An unexpected error occurred saving the spider:\n{e}")
             self._update_status_label(f"<font color='red'>Error saving {filename_hint}.</font>")
             # Finalize after error
             self._finalize_add_operation()


    @Slot(str)
    def _update_status_label(self, message):
        """Updates the status label at the bottom."""
        # Ensure this runs on the main thread for UI safety
        QtCore.QMetaObject.invokeMethod(self.status_label, "setText", Qt.QueuedConnection, QtCore.Q_ARG(str, message))


    # ( closeEvent remains the same )
    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
             self.thread.quit()
             self.thread.wait(1000)
        super().closeEvent(event)


# --- Plugin Class (remains mostly the same) ---
class Plugin(PluginBase):
    """
    Plugin to add a Spider Hub for discovering and adding pre-made spiders.
    """
    def __init__(self):
        super().__init__()
        self.name = "Spider Hub"
        self.description = "Discover and add spiders from a catalog."
        self.version = "1.1.0" # Incremented version
        self.main_window = None
        self.catalog_source = DEFAULT_SPIDERS_CATALOG_URL

    def initialize_ui(self, main_window):
        """Add menu item to trigger the Spider Hub dialog."""
        self.main_window = main_window

        if not REQUESTS_AVAILABLE and str(self.catalog_source).startswith('http'):
             logger.error(f"{self.name} requires 'requests' for remote catalog. Plugin partially disabled.")
        if not hasattr(main_window, 'project_controller'):
             logger.error(f"{self.name} requires 'project_controller'. Plugin disabled.")
             return
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

        hub_action = QAction(QIcon.fromTheme("system-search"), "Spider Hub...", main_window)
        hub_action.triggered.connect(self._show_hub_dialog)
        tools_menu.addAction(hub_action)

        logger.info(f"{self.name} plugin initialized UI.")

    @Slot()
    def _show_hub_dialog(self):
        """Shows the Spider Hub dialog."""
        if not hasattr(self.main_window, 'project_controller'):
            QMessageBox.critical(self.main_window, "Error", "Project Controller not available.")
            return

        dialog = SpiderHubDialog(self.catalog_source, self.main_window.project_controller, self.main_window)
        dialog.exec()


    def on_app_exit(self):
        logger.info(f"{self.name} plugin exiting.")
