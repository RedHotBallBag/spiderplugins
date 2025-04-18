# plugins/advanced_project_creator_plugin.py
import logging
import sys
import subprocess
import shutil
from pathlib import Path
import re
logger = logging.getLogger(__name__)
# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QPalette, QColor # Added QPalette, QColor just in case, not strictly needed here
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QMessageBox, QApplication # Import QMessageBox and QApplication

# Import Plugin Base & main window elements (potentially)
from app.plugin_base import PluginBase

# Assuming AdvancedProjectDialog is defined above as in the previous example...
# Or import it if it's in a separate file:
# from .advanced_project_dialog import AdvancedProjectDialog # Example if separated

# --- Templates and Settings ---
# (Keep ITEM_TEMPLATE and CRAWLSPIDER_TEMPLATE as before)
ITEM_TEMPLATE = """
import scrapy

class {item_class_name}(scrapy.Item):
    # define the fields for your item here like:
    field1 = scrapy.Field()
    field2 = scrapy.Field()
    # url = scrapy.Field() # Example
    pass
"""

CRAWLSPIDER_TEMPLATE = """
import scrapy
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor

class {class_name}(CrawlSpider):
    name = "{spider_name}"
    allowed_domains = ["{domain}"]
    start_urls = ["https://{domain}"] # Or http

    rules = (
        # Example rule: Extract links matching 'category.php' (replace with your rules)
        # Rule(LinkExtractor(allow=r'category\.php'), follow=True),

        # Example rule: Extract links matching 'item.php' and parse them with 'parse_item'
        Rule(LinkExtractor(allow=r'item\.php'), callback='parse_item'),
    )

    def parse_item(self, response):
        # Example: Extract data from item page
        item = {{}} # Or use your Item class: item = MyItem()
        #item['id'] = response.xpath('//td[@id="item_id"]/text()').get()
        #item['name'] = response.xpath('//h1/text()').get()
        #item['description'] = response.xpath('//div[@id="description"]').get()
        yield item
"""

# --- Project Creation Dialog ---
# (Keep AdvancedProjectDialog class definition as before)
class AdvancedProjectDialog(QtWidgets.QDialog):
    def __init__(self, default_projects_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Advanced Scrapy Project Creator")
        self.setMinimumWidth(500)
        self.default_projects_dir = Path(default_projects_dir) # Store as Path object
        self.selected_path = None # Store the chosen path

        # Layouts
        layout = QtWidgets.QVBoxLayout(self)
        form_layout = QtWidgets.QFormLayout()
        form_layout.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)

        # --- Basic Info ---
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("e.g., my_project (snake_case, valid identifier)")
        form_layout.addRow("Project Name:", self.name_input)

        path_layout = QtWidgets.QHBoxLayout()
        self.path_input = QtWidgets.QLineEdit()
        self.path_input.setPlaceholderText(f"Default: {self.default_projects_dir}/<project_name>")
        self.path_input.setReadOnly(True) # Show resolved path, don't allow direct edit
        browse_button = QtWidgets.QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_location)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(browse_button)
        form_layout.addRow("Project Location:", path_layout)

        self.desc_input = QtWidgets.QTextEdit()
        self.desc_input.setMaximumHeight(80)
        self.desc_input.setPlaceholderText("Optional description of the project.")
        form_layout.addRow("Description:", self.desc_input)

        layout.addLayout(form_layout)
        layout.addWidget(QtWidgets.QFrame(self, frameShape=QtWidgets.QFrame.Shape.HLine)) # Separator

        # --- Template and Options ---
        options_layout = QtWidgets.QVBoxLayout()
        options_layout.setSpacing(10)

        # Template
        template_group = QtWidgets.QGroupBox("Project Template")
        template_layout = QtWidgets.QVBoxLayout(template_group)
        self.template_combo = QtWidgets.QComboBox()
        self.template_combo.addItems([
            "Basic (Default Scrapy)",
            "CrawlSpider Example",
            "API Scraper (Basic Request)",
            "JavaScript Scraper (Splash)",
            "JavaScript Scraper (Playwright)",
            "Distributed Scraper (scrapy-redis)",
        ])
        template_layout.addWidget(self.template_combo)
        options_layout.addWidget(template_group)

        # Initial Settings
        settings_group = QtWidgets.QGroupBox("Initial Settings (`settings.py`)")
        settings_layout = QtWidgets.QGridLayout(settings_group)
        self.obey_robots_cb = QtWidgets.QCheckBox("Obey robots.txt (ROBOTSTXT_OBEY = True)")
        self.obey_robots_cb.setChecked(True)
        self.autothrottle_cb = QtWidgets.QCheckBox("Enable AutoThrottle")
        self.user_agent_input = QtWidgets.QLineEdit()
        self.user_agent_input.setPlaceholderText("Custom User-Agent (Optional)")
        self.download_delay_spin = QtWidgets.QDoubleSpinBox()
        self.download_delay_spin.setRange(0.0, 60.0)
        self.download_delay_spin.setDecimals(1)
        self.download_delay_spin.setValue(0.0) # Default
        self.download_delay_spin.setSuffix(" seconds")

        settings_layout.addWidget(self.obey_robots_cb, 0, 0)
        settings_layout.addWidget(self.autothrottle_cb, 0, 1)
        settings_layout.addWidget(QtWidgets.QLabel("User-Agent:"), 1, 0)
        settings_layout.addWidget(self.user_agent_input, 1, 1)
        settings_layout.addWidget(QtWidgets.QLabel("Download Delay:"), 2, 0)
        settings_layout.addWidget(self.download_delay_spin, 2, 1)
        options_layout.addWidget(settings_group)

        # Item Generation
        items_group = QtWidgets.QGroupBox("Generate Basic Item")
        items_layout = QtWidgets.QHBoxLayout(items_group)
        self.generate_item_cb = QtWidgets.QCheckBox("Create `items.py`?")
        self.item_class_name_input = QtWidgets.QLineEdit("MyItem")
        self.item_class_name_input.setPlaceholderText("Item Class Name")
        self.item_class_name_input.setEnabled(False) # Enable only if checkbox is checked
        self.generate_item_cb.toggled.connect(self.item_class_name_input.setEnabled)
        items_layout.addWidget(self.generate_item_cb)
        items_layout.addWidget(self.item_class_name_input)
        options_layout.addWidget(items_group)

        layout.addLayout(options_layout)
        layout.addStretch()

        # Spider Templates
        templates_group = QtWidgets.QGroupBox("Generate Spider Templates")
        templates_layout = QtWidgets.QVBoxLayout(templates_group)

        self.generate_templates_cb = QtWidgets.QCheckBox("Create Example Spiders?")
        templates_layout.addWidget(self.generate_templates_cb)

        # Container for spider template options (enabled only if checkbox is checked)
        self.templates_container = QtWidgets.QWidget()
        templates_container_layout = QtWidgets.QVBoxLayout(self.templates_container)
        templates_container_layout.setContentsMargins(20, 0, 0, 0)  # Add left indent

        # Spider template checkboxes
        self.basic_spider_cb = QtWidgets.QCheckBox("Basic Spider")
        self.crawl_spider_cb = QtWidgets.QCheckBox("CrawlSpider Example (with Rules)")
        self.api_spider_cb = QtWidgets.QCheckBox("API Spider Example (JSON)")

        self.basic_spider_cb.setEnabled(False)
        self.crawl_spider_cb.setEnabled(False)
        self.api_spider_cb.setEnabled(False)

        templates_container_layout.addWidget(self.basic_spider_cb)
        templates_container_layout.addWidget(self.crawl_spider_cb)
        templates_container_layout.addWidget(self.api_spider_cb)

        # Connect the template checkbox to enable/disable options
        self.generate_templates_cb.toggled.connect(self.templates_container.setEnabled)
        self.generate_templates_cb.toggled.connect(self.basic_spider_cb.setEnabled)
        self.generate_templates_cb.toggled.connect(self.crawl_spider_cb.setEnabled)
        self.generate_templates_cb.toggled.connect(self.api_spider_cb.setEnabled)

        # Add to layout
        templates_layout.addWidget(self.templates_container)
        options_layout.addWidget(templates_group)

        # --- Dialog Buttons ---
        self.button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Set initial path display
        self._update_path_display()
        self.name_input.textChanged.connect(self._update_path_display)

    @Slot()
    def _browse_location(self):
        """Opens a directory selection dialog."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select Parent Directory for Project",
            str(self.default_projects_dir.parent) # Start one level up from default
        )
        if directory:
            self.selected_path = Path(directory)
            self._update_path_display() # Update display with selected parent

    def _update_path_display(self):
         """Updates the read-only path input based on name and selected_path."""
         project_name = self.get_project_name()
         parent_dir = self.selected_path if self.selected_path else self.default_projects_dir

         # Ensure project_name is safe for path construction (basic check)
         safe_name = project_name if re.match(r"^[a-zA-Z0-9_\-]+$", project_name) else ""

         if safe_name:
             full_path = parent_dir / safe_name
             self.path_input.setText(str(full_path))
         else:
             self.path_input.setText(str(parent_dir) + "/...") # Indicate name needed


    def get_project_details(self):
        """Returns the collected project details."""
        project_name = self.get_project_name()
        parent_dir = self.selected_path if self.selected_path else self.default_projects_dir
        project_location = parent_dir / project_name

        return {
            "name": project_name,
            "location": str(project_location),
            "parent_dir": str(parent_dir),
            "description": self.desc_input.toPlainText().strip(),
            "template": self.template_combo.currentText(),
            "settings": {
                "ROBOTSTXT_OBEY": self.obey_robots_cb.isChecked(),
                "AUTOTHROTTLE_ENABLED": self.autothrottle_cb.isChecked(),
                "USER_AGENT": self.user_agent_input.text().strip() or None,
                "DOWNLOAD_DELAY": self.download_delay_spin.value() if self.download_delay_spin.value() > 0 else None
            },
            "generate_item": self.generate_item_cb.isChecked(),
            "item_class_name": self.item_class_name_input.text().strip() if self.generate_item_cb.isChecked() else None,
            "generate_spiders": self.generate_templates_cb.isChecked(),
            "spider_templates": {
                "basic": self.basic_spider_cb.isChecked(),
                "crawl": self.crawl_spider_cb.isChecked(),
                "api": self.api_spider_cb.isChecked()
            }
        }

    def get_project_name(self):
         """Gets the project name safely."""
         return self.name_input.text().strip()

    def accept(self):
        """Validate input before accepting."""
        name = self.get_project_name()
        if not name:
            QMessageBox.warning(self, "Input Error", "Project Name cannot be empty.")
            return
        # Basic validation for directory/python identifier name
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            QMessageBox.warning(self, "Input Error", "Project Name must be a valid Python identifier (start with letter or _, contain letters, numbers, _).")
            return

        # Check if item class name is valid if needed
        if self.generate_item_cb.isChecked():
            item_name = self.item_class_name_input.text().strip()
            if not item_name or not re.match(r"^[A-Z][a-zA-Z0-9_]*$", item_name):
                 QMessageBox.warning(self, "Input Error", "Item Class Name must be a valid Python class name (Start with uppercase, contain letters, numbers, _).")
                 return

        # Check if target directory already exists
        # Recalculate location based on potentially changed name
        parent_dir = self.selected_path if self.selected_path else self.default_projects_dir
        project_location = parent_dir / name
        if project_location.exists():
             reply = QMessageBox.question(
                  self, "Directory Exists",
                  f"The directory:\n{project_location}\nalready exists. Continue anyway? (Files might be overwritten)",
                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No
             )
             if reply == QMessageBox.No:
                  return # Don't accept if user cancels

        super().accept() # Proceed if validation passes


# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Plugin to add an Advanced Scrapy Project Creator.
    """
    def __init__(self):
        super().__init__()
        self.name = "Advanced Project Creator"
        self.description = "Creates new Scrapy projects with templates and initial settings."
        self.version = "1.0.1" # Version bump
        self.main_window = None

    def initialize_ui(self, main_window):
        """Add menu item to trigger the project creation dialog."""
        logger.debug(f"Attempting to initialize UI for {self.name}...")
        self.main_window = main_window

        # --- Essential Checks ---
        if not hasattr(main_window, 'project_controller'):
            logger.error(f"{self.name} requires 'project_controller'. Skipping UI init.")
            return
        if not hasattr(main_window, 'menuBar'):
            logger.error(f"{self.name}: Main window has no 'menuBar'. Skipping menu item add.")
            return
        logger.debug(f"{self.name}: Found menuBar and project_controller.")

        menubar = main_window.menuBar()
        file_menu_action = None # The QAction that owns the File menu
        target_menu_title_lower = "file"

        # --- Find File Menu Action ---
        logger.debug(f"{self.name}: Searching for File menu action...")
        for action in menubar.actions():
            action_text = action.text().strip().replace('&', '')
            if action.menu() and action_text.lower() == target_menu_title_lower:
                file_menu_action = action
                logger.info(f"{self.name}: Found action for File menu: '{action.text()}'")
                break

        if not file_menu_action:
            logger.error(f"{self.name}: Could not find the action associated with the '{target_menu_title_lower.capitalize()}' menu.")
            return

        # --- Get the QMenu right before using it ---
        file_menu = file_menu_action.menu()
        if not file_menu:
            logger.error(f"{self.name}: Action '{file_menu_action.text()}' found but it has no QMenu!")
            return
        logger.debug(f"{self.name}: Successfully obtained QMenu for File.")

        # --- Create the new QAction ---
        adv_new_action = QAction(QIcon.fromTheme("document-new"), "New Project (Advanced)...", main_window)
        adv_new_action.setToolTip("Create a new Scrapy project with more options")
        adv_new_action.triggered.connect(self._show_create_dialog)
        logger.debug(f"{self.name}: Created 'New Project (Advanced)...' QAction.")

        # --- Find the basic "New Project" action to insert before ---
        new_project_basic_action = None
        target_basic_action_text_lower = "new project"
        logger.debug(f"{self.name}: Searching for basic 'New Project' action in File menu...")
        for action in file_menu.actions():
            action_text = action.text().strip().replace('&', '')
            if not action.isSeparator() and action_text.lower() == target_basic_action_text_lower:
                new_project_basic_action = action
                logger.info(f"{self.name}: Found basic 'New Project' action: '{action.text()}'")
                break

        # --- Insert or Append the Action ---
        try:
            if new_project_basic_action:
                logger.info(f"{self.name}: Inserting 'Advanced...' action before '{new_project_basic_action.text()}'")
                # Insert the new action *before* the basic one
                file_menu.insertAction(new_project_basic_action, adv_new_action)
                # Insert separator *after* the newly inserted action
                file_menu.insertSeparator(new_project_basic_action) # Insert sep before the basic one now
                logger.info(f"{self.name}: Successfully inserted action and separator.")
            else:
                logger.warning(f"{self.name}: Basic 'New Project' action not found. Appending 'Advanced...' to end.")
                file_menu.addAction(adv_new_action) # Add at the end
                logger.info(f"{self.name}: Successfully appended action.")

        except Exception as e:
            logger.error(f"{self.name}: Error adding action/separator to File menu: {e}", exc_info=True)
            # Don't stop the app, just log the failure
            return # Stop further UI init for this plugin

        logger.info(f"{self.name} plugin UI initialization finished.")

    # --- Rest of the methods (_show_create_dialog, _create_project_with_options, etc.) ---
    # --- remain the same as in the previous version ---
    @Slot()
    def _show_create_dialog(self):
        """Shows the advanced project creation dialog."""
        if not hasattr(self.main_window, 'project_controller'):
            QMessageBox.critical(self.main_window, "Error", "Project Controller not available.")
            return

        # Get default location from project controller
        default_dir = self.main_window.project_controller.projects_dir

        dialog = AdvancedProjectDialog(default_dir, self.main_window)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            details = dialog.get_project_details()
            self._create_project_with_options(details)

    def _create_project_with_options(self, details):
        """Handles the actual project creation and modification."""
        project_name = details['name']

        # Check for problematic project names
        problematic_names = ["django", "scrapy", "twisted", "os", "sys", "json"]
        if project_name.lower() in problematic_names:
            # Show warning and ask to confirm or change name
            reply = QtWidgets.QMessageBox.warning(
                self.main_window,
                "Potentially Problematic Project Name",
                f"'{project_name}' is a name of an existing Python package which might cause conflicts.\n\n"
                "Would you like to continue with this name anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.No:
                return False
        # Use parent_dir from details for clarity
        project_parent_dir = Path(details['parent_dir'])
        project_location = project_parent_dir / project_name # This is the outer folder scrapy creates
        project_module_path = project_location / project_name # This is the inner folder with settings.py


        logger.info(f"Attempting to create advanced project '{project_name}' at '{project_location}'")
        self.main_window.statusBar().showMessage(f"Creating project {project_name}...")
        QApplication.processEvents() # Update UI

        # --- 1. Run scrapy startproject ---
        try:
            # Create parent directory if it doesn't exist
            project_parent_dir.mkdir(parents=True, exist_ok=True)

            cmd = ["scrapy", "startproject", project_name]
            # Run in the *parent* directory
            result = subprocess.run(
                 cmd,
                 cwd=str(project_parent_dir), # Run in parent dir
                 check=True, # Raise exception on error
                 capture_output=True,
                 text=True,
                 encoding='utf-8',
                 startupinfo=None # Avoid potential issues on Windows with complex startup info
             )
            
            logger.info(f"Scrapy startproject successful for {project_name}.")
            logger.debug(f"startproject stdout:\n{result.stdout}")

        except FileNotFoundError:
            logger.error("`scrapy` command not found. Is Scrapy installed and in PATH?")
            QMessageBox.critical(self.main_window, "Scrapy Not Found", "`scrapy` command not found.\nPlease ensure Scrapy is installed and accessible in your system's PATH.")
            self.main_window.statusBar().showMessage("Project creation failed: Scrapy not found.", 5000)
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running `scrapy startproject`: {e}")
            logger.error(f"Stderr:\n{e.stderr}")
            QMessageBox.critical(self.main_window, "Scrapy Error", f"Scrapy command failed:\n{e.stderr}")
            self.main_window.statusBar().showMessage(f"Project creation failed: {e}", 5000)
            # Clean up potentially partially created folder?
            if project_location.exists():
                 logger.info(f"Attempting to clean up failed project directory: {project_location}")
                 try:
                      shutil.rmtree(project_location)
                 except Exception as rm_err:
                      logger.error(f"Failed to remove directory after error: {rm_err}")
            return False
        except Exception as e:
             logger.exception("Unexpected error during project creation subprocess:")
             QMessageBox.critical(self.main_window, "Error", f"An unexpected error occurred:\n{e}")
             self.main_window.statusBar().showMessage(f"Project creation failed: {e}", 5000)
             return False

        # --- 2. Post-creation modifications ---
        try:
            self.main_window.statusBar().showMessage(f"Configuring project {project_name}...")
            QApplication.processEvents()

            # Modify settings.py (use project_module_path)
            self._modify_settings(project_module_path / 'settings.py', details['settings'])

            # Generate items.py (use project_module_path)
            if details['generate_item']:
                self._generate_items_file(project_module_path / 'items.py', details['item_class_name'])
            # Install dependencies based on template
            template_name = details['template']
            try:
                if "Splash" in template_name:
                    subprocess.run(["pip", "install", "scrapy-splash"], check=False)
                elif "Playwright" in template_name:
                    subprocess.run(["pip", "install", "scrapy-playwright"], check=False)
                    subprocess.run(["playwright", "install"], check=False)
                elif "Distributed" in template_name:
                    subprocess.run(["pip", "install", "scrapy-redis"], check=False)
                
            except Exception as dep_error:
                logger.warning(f"Optional dependency install failed: {dep_error}")
                # Apply template modifications (spiders) (use project_module_path)
            self._apply_template(project_module_path, details['template'], project_name)

        except Exception as e:
             logger.exception(f"Error during post-creation modification for {project_name}:")
             QMessageBox.warning(self.main_window, "Configuration Warning", f"Project created, but failed during post-creation configuration:\n{e}")
             # Project exists, proceed to add it anyway

        # --- 3. Add to Project Controller ---
        # Use the *outer* directory where scrapy.cfg resides for the controller
        success = self.main_window.project_controller.add_project(
             path=str(project_location), # Path to the outer project dir containing scrapy.cfg
             name=project_name, # Use the provided name
             description=details['description']
             )

        if success:
            # If spider templates requested, create them
            if details.get('generate_spiders', False):
                self._generate_spider_templates(
                    project_path=project_location,
                    project_name=project_name,
                    templates=details.get('spider_templates', {}),
                    project_type=details.get('template')
                )
            logger.info(f"Successfully added project '{project_name}' to manager.")
            self.main_window.statusBar().showMessage(f"Project '{project_name}' created successfully!", 5000)
            # Refresh project list and select the new one
            if hasattr(self.main_window, '_load_projects'):
                 self.main_window._load_projects()
                 for i in range(self.main_window.project_list.count()):
                    item = self.main_window.project_list.item(i)
                    if item and item.text() == project_name:
                        self.main_window.project_list.setCurrentItem(item)
                        if hasattr(self.main_window, '_on_project_selected'):
                            QtCore.QTimer.singleShot(100, lambda item=item: self.main_window._on_project_selected(item))
                        break
                 # Find and select the item in the list
                 if hasattr(self.main_window, 'project_list'):
                      for i in range(self.main_window.project_list.count()):
                           item = self.main_window.project_list.item(i)
                           if item and item.text() == project_name:
                                self.main_window.project_list.setCurrentItem(item)
                                # Trigger the selection handler manually if needed
                                if hasattr(self.main_window, '_on_project_selected'):
                                     QtCore.QTimer.singleShot(100, lambda item=item: self.main_window._on_project_selected(item)) # Delay slightly
                                break
            return True
        else:
            logger.error(f"Project '{project_name}' created on disk, but failed to add to manager (already exists?).")
            QMessageBox.warning(self.main_window, "Add Error", f"Project '{project_name}' was created, but could not be added to the project list (maybe the name already exists?).")
            # Refresh list anyway to ensure consistency
            if hasattr(self.main_window, '_load_projects'):
                 self.main_window._load_projects()
            return False
        
       
    

    def _modify_settings(self, settings_path, settings_values):
        """Modifies the generated settings.py file."""
        if not settings_path.exists():
            logger.warning(f"settings.py not found at {settings_path}. Skipping modifications.")
            return

        try:
            content = settings_path.read_text(encoding='utf-8')
            lines = content.splitlines()
            new_lines = []

            # Flags to track if settings were found and modified
            modified = {key: False for key in settings_values}

            for line in lines:
                processed_line = line
                strip_line = line.strip()

                # Robots
                if strip_line.startswith('ROBOTSTXT_OBEY'):
                    processed_line = f"ROBOTSTXT_OBEY = {settings_values['ROBOTSTXT_OBEY']}"
                    modified['ROBOTSTXT_OBEY'] = True
                # AutoThrottle
                elif strip_line.startswith('#AUTOTHROTTLE_ENABLED'):
                    if settings_values['AUTOTHROTTLE_ENABLED']:
                        processed_line = "AUTOTHROTTLE_ENABLED = True"
                        modified['AUTOTHROTTLE_ENABLED'] = True
                    # Keep it commented if not enabled
                elif strip_line.startswith('AUTOTHROTTLE_ENABLED'): # If already uncommented
                    processed_line = f"AUTOTHROTTLE_ENABLED = {settings_values['AUTOTHROTTLE_ENABLED']}"
                    modified['AUTOTHROTTLE_ENABLED'] = True

                # User-Agent
                elif strip_line.startswith('#USER_AGENT'):
                    if settings_values['USER_AGENT']:
                         processed_line = f"USER_AGENT = '{settings_values['USER_AGENT']}'" # Use f-string quote style
                         modified['USER_AGENT'] = True
                elif strip_line.startswith('USER_AGENT'): # If already uncommented
                     if settings_values['USER_AGENT']:
                         processed_line = f"USER_AGENT = '{settings_values['USER_AGENT']}'"
                     else: # Comment it out if user cleared it
                          processed_line = f"#{line}" # Just comment out the whole original line
                     modified['USER_AGENT'] = True

                # Download Delay
                elif strip_line.startswith('#DOWNLOAD_DELAY'):
                     if settings_values['DOWNLOAD_DELAY'] is not None:
                          processed_line = f"DOWNLOAD_DELAY = {settings_values['DOWNLOAD_DELAY']}"
                          modified['DOWNLOAD_DELAY'] = True
                elif strip_line.startswith('DOWNLOAD_DELAY'): # If already uncommented
                     if settings_values['DOWNLOAD_DELAY'] is not None:
                          processed_line = f"DOWNLOAD_DELAY = {settings_values['DOWNLOAD_DELAY']}"
                     else: # Comment it out if user set to 0
                           processed_line = f"#{line}" # Just comment out the whole original line
                     modified['DOWNLOAD_DELAY'] = True


                new_lines.append(processed_line)

            # Add settings if they were not found in the template (append at the end)
            # This ensures user settings are applied even if the template changes
            appended_settings = False
            for key, val in settings_values.items():
                 if not modified[key] and val is not None: # Only add if not found and value is meaningful
                    setting_line = ""
                    if key == 'ROBOTSTXT_OBEY': setting_line = f"ROBOTSTXT_OBEY = {val}"
                    elif key == 'AUTOTHROTTLE_ENABLED': setting_line = f"AUTOTHROTTLE_ENABLED = {val}"
                    elif key == 'USER_AGENT': setting_line = f"USER_AGENT = '{val}'"
                    elif key == 'DOWNLOAD_DELAY': setting_line = f"DOWNLOAD_DELAY = {val}"

                    if setting_line:
                         if not appended_settings: # Add a separator line before the first appended setting
                              new_lines.extend(["", "# --- Settings added by Advanced Project Creator ---"])
                              appended_settings = True
                         new_lines.append(setting_line)
                         logger.debug(f"Setting '{key}' not found in template, appending.")


            settings_path.write_text("\n".join(new_lines) + "\n", encoding='utf-8') # Add trailing newline
            logger.info(f"Modified settings.py at {settings_path}")

        except Exception as e:
            logger.error(f"Error modifying settings file {settings_path}: {e}", exc_info=True)
            raise # Re-raise to notify user in the main function

    def _generate_items_file(self, items_path, item_class_name):
        """Creates a basic items.py file."""
        if not item_class_name:
             item_class_name = "MyItem" # Default

        # Ensure class name is valid (basic check)
        safe_item_class_name = "".join(c for c in item_class_name if c.isalnum() or c == '_')
        if not safe_item_class_name or not safe_item_class_name[0].isalpha() or not safe_item_class_name[0].isupper():
             logger.warning(f"Invalid item class name '{item_class_name}', using 'MyItem'.")
             safe_item_class_name = "MyItem" # Fallback to default if invalid

        try:
            item_code = ITEM_TEMPLATE.format(item_class_name=safe_item_class_name)
            items_path.write_text(item_code, encoding='utf-8')
            logger.info(f"Generated items.py at {items_path} with class {safe_item_class_name}")
        except Exception as e:
            logger.error(f"Error generating items file {items_path}: {e}", exc_info=True)
            raise

    def _apply_template(self, project_module_path, template_name, project_name):
        """Applies template modifications, e.g., adding specific spiders."""
        spiders_dir = project_module_path / 'spiders'
        if not spiders_dir.exists():
             logger.warning(f"Spiders directory not found at {spiders_dir}. Cannot apply template.")
             return

        # Ensure project_name is a valid spider name (already validated for directory name)
        spider_name_base = project_name

        if template_name == "Basic (Default Scrapy)":
            # Rename the default spider if needed? No, startproject already does this.
            logger.info("Using basic Scrapy template (no spider modifications needed).")
            return

        elif template_name == "CrawlSpider Example":
            logger.info("Applying CrawlSpider template...")
            # Create a basic CrawlSpider
            spider_name = f"{spider_name_base}_crawler"
            class_name = "".join(word.capitalize() for word in spider_name.split('_'))
            # Guess a domain from project name or use example.com
            # Let's just use example.com as placeholder
            domain = "example.com"

            spider_code = CRAWLSPIDER_TEMPLATE.format(
                class_name=class_name,
                spider_name=spider_name,
                domain=domain
            )
            spider_file_path = spiders_dir / f"{spider_name}.py"
            try:
                spider_file_path.write_text(spider_code, encoding='utf-8')
                logger.info(f"Created example CrawlSpider: {spider_file_path.name}")
                # Optionally remove the default basic spider created by startproject
                # Default name should be project_name.py
                default_spider_path = spiders_dir / f"{spider_name_base}.py"
                if default_spider_path.exists():
                     try:
                          default_spider_path.unlink()
                          logger.info(f"Removed default spider file: {default_spider_path.name}")
                     except OSError as e:
                          logger.error(f"Could not remove default spider {default_spider_path}: {e}")

            except Exception as e:
                 logger.error(f"Failed to write CrawlSpider template: {e}")
                 raise
        elif template_name == "JavaScript Scraper (Splash)":
            logger.info("Applying Splash JavaScript scraping setup...")
            settings_path = project_module_path / 'settings.py'
            with open(settings_path, "a", encoding="utf-8") as f:
                f.write("\n# Splash Integration\n")
                f.write("SPLASH_URL = 'http://localhost:8050'\n")
                f.write("DOWNLOADER_MIDDLEWARES = {\n")
                f.write("    'scrapy_splash.SplashCookiesMiddleware': 723,\n")
                f.write("    'scrapy_splash.SplashMiddleware': 725,\n")
                f.write("    'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 810,\n")
                f.write("}\n")
                f.write("SPIDER_MIDDLEWARES = {\n")
                f.write("    'scrapy_splash.SplashDeduplicateArgsMiddleware': 100,\n")
                f.write("}\n")
                f.write("DUPEFILTER_CLASS = 'scrapy_splash.SplashAwareDupeFilter'\n")
                f.write("HTTPCACHE_STORAGE = 'scrapy_splash.SplashAwareFSCacheStorage'\n")
            logger.info("Splash settings added.")

        elif template_name == "JavaScript Scraper (Playwright)":
            logger.info("Applying Playwright JavaScript scraping setup...")
            settings_path = project_module_path / 'settings.py'
            with open(settings_path, "a", encoding="utf-8") as f:
                f.write("\n# Playwright Integration\n")
                f.write("DOWNLOAD_HANDLERS = {\n")
                f.write("    'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',\n")
                f.write("    'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',\n")
                f.write("}\n")
                f.write("TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'\n")
            logger.info("Playwright settings added.")

        elif template_name == "Distributed Scraper (scrapy-redis)":
            logger.info("Applying scrapy-redis distributed setup...")
            settings_path = project_module_path / 'settings.py'
            with open(settings_path, "a", encoding="utf-8") as f:
                f.write("\n# Scrapy-Redis Integration\n")
                f.write("DUPEFILTER_CLASS = 'scrapy_redis.dupefilter.RFPDupeFilter'\n")
                f.write("SCHEDULER = 'scrapy_redis.scheduler.Scheduler'\n")
                f.write("SCHEDULER_PERSIST = True\n")
                f.write("# REDIS_HOST = 'localhost'\n")
                f.write("# REDIS_PORT = 6379\n")
            logger.info("Scrapy-Redis settings added.")

            
        elif template_name == "API Scraper (Basic Request)":
            logger.info("Applying API Scraper template...")
            # Overwrite the default spider
            default_spider_path = spiders_dir / f"{spider_name_base}.py"
            if default_spider_path.exists():
                try:
                    # Ensure class name is valid (CamelCase version of project_name)
                    class_name_api = "".join(word.capitalize() for word in spider_name_base.split('_'))
                    api_spider_code = f"""
import scrapy
import json # Import json module

class {class_name_api}Spider(scrapy.Spider):
    name = "{spider_name_base}"
    # allowed_domains = ["api.example.com"] # TODO: User should set this
    start_urls = ["https://httpbin.org/get"] # Example API endpoint

    def parse(self, response):
        self.logger.info(f"Received response from {{response.url}}")
        try:
            # Attempt to parse JSON
            data = response.json()
            self.logger.info(f"Successfully parsed JSON data.")
            # TODO: Process the JSON data here
            yield {{'api_data': data}}
        except json.JSONDecodeError:
            self.logger.error(f"Failed to decode JSON from {{response.url}}. Response body: {{response.text[:500]}}") # Log start of body
        except Exception as e:
            self.logger.error(f"Error processing response: {{e}}", exc_info=True) # Log traceback for other errors

"""
                    default_spider_path.write_text(api_spider_code, encoding='utf-8')
                    logger.info(f"Overwrote default spider with basic API scraping template.")
                except Exception as e:
                     logger.error(f"Failed to modify spider for API template: {e}")
                     raise
            else:
                logger.warning(f"Default spider file '{default_spider_path.name}' not found. Cannot apply API template modifications.")


    def on_app_exit(self):
        """Placeholder for cleanup if needed."""
        logger.info(f"{self.name} plugin exiting.")

    def _generate_spider_templates(self, project_path, project_name, templates, project_type):
        """Generates requested spider template files."""
        spiders_dir = Path(project_path) / project_name / "spiders"
        if not spiders_dir.exists():
            logger.warning(f"Spiders directory not found at {spiders_dir}, cannot generate templates.")
            return
        
        domain = "example.com"  # Default domain
        
        # Generate basic spider if requested
        if templates.get('basic', False):
            basic_spider_name = f"basic_{project_name}"
            basic_spider_path = spiders_dir / f"{basic_spider_name}.py"
            
            basic_spider_code = (
                "import scrapy\n\n\n"
                f"class BasicExampleSpider(scrapy.Spider):\n"
                f"    name = \"{basic_spider_name}\"\n"
                f"    allowed_domains = [\"{domain}\"]\n"
                f"    start_urls = [\"https://{domain}\"]\n\n"
                f"    def parse(self, response):\n"
                f"        \"\"\"Process the response and extract data.\"\"\"\n"
                f"        self.logger.info(f\"Successfully crawled: {{response.url}}\")\n"
                f"        \n"
                f"        # Extract all links\n"
                f"        for link in response.css('a::attr(href)').getall():\n"
                f"            yield {{'link': link}}\n"
                f"            \n"
                f"        # Example: Extract all headings\n"
                f"        for heading in response.css('h1, h2, h3::text').getall():\n"
                f"            yield {{'heading': heading}}\n"
            )
            
            try:
                with open(basic_spider_path, 'w', encoding='utf-8') as f:
                    f.write(basic_spider_code)
                logger.info(f"Generated basic spider template: {basic_spider_path}")
            except Exception as e:
                logger.error(f"Error creating basic spider template: {e}")
        
        # Generate CrawlSpider if requested
        if templates.get('crawl', False):
            crawl_spider_name = f"crawl_{project_name}"
            crawl_spider_path = spiders_dir / f"{crawl_spider_name}.py"
            
            crawl_spider_code = (
                "import scrapy\n"
                "from scrapy.spiders import CrawlSpider, Rule\n"
                "from scrapy.linkextractors import LinkExtractor\n\n\n"
                f"class CrawlExampleSpider(CrawlSpider):\n"
                f"    name = \"{crawl_spider_name}\"\n"
                f"    allowed_domains = [\"{domain}\"]\n"
                f"    start_urls = [\"https://{domain}\"]\n\n"
                f"    # Define crawling rules\n"
                f"    rules = (\n"
                f"        # Rule for following category links\n"
                f"        Rule(LinkExtractor(allow=r'category/'), follow=True),\n"
                f"        \n"
                f"        # Rule for extracting data from product pages\n"
                f"        Rule(LinkExtractor(allow=r'product/'), callback='parse_item'),\n"
                f"    )\n"
                f"    \n"
                f"    def parse_item(self, response):\n"
                f"        \"\"\"Process each item page and extract data.\"\"\"\n"
                f"        self.logger.info(f\"Processing item page: {{response.url}}\")\n"
                f"        \n"
                f"        yield {{\n"
                f"            'url': response.url,\n"
                f"            'title': response.css('h1::text').get(),\n"
                f"            'price': response.css('.price::text').get(),\n"
                f"            'description': response.css('.description::text').get(),\n"
                f"        }}\n"
            )
            
            try:
                with open(crawl_spider_path, 'w', encoding='utf-8') as f:
                    f.write(crawl_spider_code)
                logger.info(f"Generated CrawlSpider template: {crawl_spider_path}")
            except Exception as e:
                logger.error(f"Error creating CrawlSpider template: {e}")
        
        # Generate API spider if requested
        if templates.get('api', False):
            api_spider_name = f"api_{project_name}"
            api_spider_path = spiders_dir / f"{api_spider_name}.py"
            
            # Adjust the API spider template based on project type
            if "Playwright" in project_type:
                # Fix: Use string concatenation to avoid indentation issues
                api_spider_code = (
                    "import scrapy\n"
                    "import json\n\n\n"
                    f"class ApiExampleSpider(scrapy.Spider):\n"
                    f"    name = \"{api_spider_name}\"\n"
                    f"    allowed_domains = [\"httpbin.org\"]\n"
                    f"    start_urls = [\"https://httpbin.org/get\"]\n\n"
                    f"    custom_settings = {{\n"
                    f"        'PLAYWRIGHT_LAUNCH_OPTIONS': {{'headless': True}},\n"
                    f"    }}\n\n"
                    f"    def start_requests(self):\n"
                    f"        # Example of an API request with Playwright\n"
                    f"        for url in self.start_urls:\n"
                    f"            yield scrapy.Request(\n"
                    f"                url=url,\n"
                    f"                callback=self.parse,\n"
                    f"                meta={{'playwright': True}}  # Enable Playwright for this request\n"
                    f"            )\n\n"
                    f"    def parse(self, response):\n"
                    f"        \"\"\"Process API response data.\"\"\"\n"
                    f"        self.logger.info(f\"Processing API response from: {{response.url}}\")\n"
                    f"        \n"
                    f"        try:\n"
                    f"            # Parse JSON response\n"
                    f"            data = response.json()\n"
                    f"            self.logger.info(f\"Successfully parsed JSON data\")\n"
                    f"            \n"
                    f"            # Extract relevant information\n"
                    f"            yield {{\n"
                    f"                'url': response.url,\n"
                    f"                'headers': data.get('headers', {{}}),\n"
                    f"                'args': data.get('args', {{}}),\n"
                    f"                'origin': data.get('origin'),\n"
                    f"            }}\n"
                    f"            \n"
                    f"        except json.JSONDecodeError:\n"
                    f"            self.logger.error(f\"Failed to decode JSON from {{response.url}}\")\n"
                )
            else:
                # Fix: Use string concatenation to avoid indentation issues
                api_spider_code = (
                    "import scrapy\n"
                    "import json\n\n\n"
                    f"class ApiExampleSpider(scrapy.Spider):\n"
                    f"    name = \"{api_spider_name}\"\n"
                    f"    allowed_domains = [\"httpbin.org\"]\n"
                    f"    \n"
                    f"    # Start with a simple API endpoint for testing\n"
                    f"    start_urls = [\"https://httpbin.org/get\"]\n\n"
                    f"    def parse(self, response):\n"
                    f"        \"\"\"Process API response data.\"\"\"\n"
                    f"        self.logger.info(f\"Processing API response from: {{response.url}}\")\n"
                    f"        \n"
                    f"        try:\n"
                    f"            # Parse JSON response\n"
                    f"            data = response.json()\n"
                    f"            self.logger.info(f\"Successfully parsed JSON data\")\n"
                    f"            \n"
                    f"            # Extract relevant information\n"
                    f"            yield {{\n"
                    f"                'url': response.url,\n"
                    f"                'headers': data.get('headers', {{}}),\n"
                    f"                'args': data.get('args', {{}}),\n"
                    f"                'origin': data.get('origin'),\n"
                    f"            }}\n"
                    f"            \n"
                    f"            # Example: Make a POST request\n"
                    f"            yield scrapy.Request(\n"
                    f"                url=\"https://httpbin.org/post\",\n"
                    f"                method=\"POST\",\n"
                    f"                body=json.dumps({{'key': 'value'}}),\n"
                    f"                headers={{'Content-Type': 'application/json'}},\n"
                    f"                callback=self.parse_post\n"
                    f"            )\n"
                    f"            \n"
                    f"        except json.JSONDecodeError:\n"
                    f"            self.logger.error(f\"Failed to decode JSON from {{response.url}}\")\n"
                    f"    \n"
                    f"    def parse_post(self, response):\n"
                    f"        \"\"\"Handle POST response.\"\"\"\n"
                    f"        try:\n"
                    f"            data = response.json()\n"
                    f"            yield {{\n"
                    f"                'url': response.url,\n"
                    f"                'method': 'POST',\n"
                    f"                'data': data.get('json', {{}}),\n"
                    f"                'headers': data.get('headers', {{}})\n"
                    f"            }}\n"
                    f"        except json.JSONDecodeError:\n"
                    f"            self.logger.error(f\"Failed to decode JSON from POST response\")\n"
                )
            
            try:
                with open(api_spider_path, 'w', encoding='utf-8') as f:
                    f.write(api_spider_code)
                logger.info(f"Generated API spider template: {api_spider_path}")
            except Exception as e:
                logger.error(f"Error creating API spider template: {e}")