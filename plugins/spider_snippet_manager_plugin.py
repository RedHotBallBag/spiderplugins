import datetime
import logging
import sys
import json
from pathlib import Path
import re

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QTreeWidget, QTreeWidgetItem, QPushButton, QToolBar,
                               QDialogButtonBox, QMessageBox, QSizePolicy, QWidget,
                               QPlainTextEdit, QLineEdit, QComboBox, QFormLayout,
                               QSpacerItem, QDockWidget, QSplitter, QGroupBox) # Added QGroupBox
from PySide6.QtCore import Qt, Slot, Signal

# Import Plugin Base
from app.plugin_base import PluginBase
# Try to import editor components for syntax highlighting preview
try:
    from app.editor.code_editor import PythonHighlighter
    HIGHLIGHTER_AVAILABLE = True
except ImportError:
    HIGHLIGHTER_AVAILABLE = False
    logging.warning("Snippet Manager: PythonHighlighter not found. Snippet preview will not be highlighted.")


logger = logging.getLogger(__name__)

# --- Default Snippets (Optional) ---
DEFAULT_SNIPPETS = [
    {
        "id": "css_basic_get",
        "name": "Basic CSS Selector (.get)",
        "category": "Selectors",
        "description": "Extracts the first text() or attribute using CSS.",
        "code": "response.css('your_selector::text').get()",
    },
    {
        "id": "css_basic_getall",
        "name": "Basic CSS Selector (.getall)",
        "category": "Selectors",
        "description": "Extracts all matching text() or attributes using CSS.",
        "code": "response.css('your_selector::attr(href)').getall()",
    },
    {
        "id": "xpath_basic_get",
        "name": "Basic XPath Selector (.get)",
        "category": "Selectors",
        "description": "Extracts the first text() or attribute using XPath.",
        "code": "response.xpath('//your_selector/text()').get()",
    },
    {
        "id": "xpath_basic_getall",
        "name": "Basic XPath Selector (.getall)",
        "category": "Selectors",
        "description": "Extracts all matching text() or attributes using XPath.",
        "code": "response.xpath('//your_selector/@href').getall()",
    },
    {
        "id": "item_field",
        "name": "Item Field Definition",
        "category": "Items",
        "description": "Defines a field in a scrapy.Item.",
        "code": "my_field_name = scrapy.Field()",
    },
    {
        "id": "basic_yield_dict",
        "name": "Yield Dictionary",
        "category": "Spiders",
        "description": "Yield a simple dictionary from the parse method.",
        "code": "yield {\n    'field1': response.css('selector1::text').get(),\n    'field2': response.xpath('//selector2/@attr').get(),\n    'url': response.url,\n}",
    },
    {
        "id": "follow_next_page",
        "name": "Follow Next Page Link",
        "category": "Spiders",
        "description": "Standard pattern for following pagination links.",
        "code": "next_page = response.css('a.next::attr(href)').get() # Adjust selector\nif next_page is not None:\n    yield response.follow(next_page, self.parse)",
    },
    {
        "id": "item_loader_basic",
        "name": "Basic Item Loader Usage",
        "category": "Item Loaders",
        "description": "Load data into an Item using ItemLoader.",
        "code": "from itemloaders.processors import TakeFirst\nfrom scrapy.loader import ItemLoader\n# from ..items import YourItemClass # Adjust import\n\ndef parse_item(self, response):\n    loader = ItemLoader(item=YourItemClass(), response=response)\n    loader.default_output_processor = TakeFirst()\n\n    loader.add_css('name', 'h1::text')\n    loader.add_xpath('price', '//span[@class=\"price\"]/text()')\n    # ... add more fields\n\n    yield loader.load_item()",
    },
]


# --- Snippet Editor Dialog ---
class SnippetEditDialog(QDialog):
    """Dialog for adding or editing snippets."""
    def __init__(self, snippet_data=None, existing_categories=None, parent=None):
        super().__init__(parent)
        self.snippet_data = snippet_data or {} # Store existing data if editing
        self.existing_categories = existing_categories or ["General", "Selectors", "Items", "Spiders", "Pipelines", "Item Loaders"]

        self.setWindowTitle("Edit Snippet" if snippet_data else "Add New Snippet")
        self.setMinimumSize(550, 450)

        self._init_ui()
        if snippet_data:
            self._populate_fields()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Short, descriptive name")
        form_layout.addRow("Name:", self.name_input)

        self.category_combo = QComboBox()
        self.category_combo.addItems(sorted(list(set(self.existing_categories)))) # Unique, sorted
        self.category_combo.setEditable(True) # Allow adding new categories
        form_layout.addRow("Category:", self.category_combo)

        self.desc_input = QtWidgets.QTextEdit()
        self.desc_input.setPlaceholderText("Optional: What this snippet does or how to use it.")
        self.desc_input.setMaximumHeight(80)
        form_layout.addRow("Description:", self.desc_input)

        self.code_input = QPlainTextEdit()
        code_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        code_font.setPointSize(10)
        self.code_input.setFont(code_font)
        self.code_input.setPlaceholderText("Paste or write your code snippet here.")
        if HIGHLIGHTER_AVAILABLE:
             try:
                 self.highlighter = PythonHighlighter(self.code_input.document())
             except Exception as e:
                  logger.warning(f"Could not apply highlighter in SnippetEditDialog: {e}")

        form_layout.addRow("Code:", self.code_input)

        layout.addLayout(form_layout)

        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _populate_fields(self):
        """Fill fields if editing existing data."""
        self.name_input.setText(self.snippet_data.get("name", ""))
        self.desc_input.setText(self.snippet_data.get("description", ""))
        self.code_input.setPlainText(self.snippet_data.get("code", ""))
        category = self.snippet_data.get("category", "General")
        # Select existing category or add if new
        index = self.category_combo.findText(category)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        else:
            self.category_combo.addItem(category)
            self.category_combo.setCurrentText(category)


    def get_snippet_data(self):
        """Return the data entered by the user."""
        snippet_id = self.snippet_data.get("id") # Keep existing ID if editing
        if not snippet_id:
            # Generate a simple ID for new snippets
            snippet_id = f"snippet_{int(datetime.now().timestamp())}"

        category = self.category_combo.currentText().strip() or "General"

        return {
            "id": snippet_id,
            "name": self.name_input.text().strip(),
            "category": category,
            "description": self.desc_input.toPlainText().strip(),
            "code": self.code_input.toPlainText() # Keep original formatting, including leading/trailing whitespace
        }

    def accept(self):
        # Basic validation
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Input Error", "Snippet Name cannot be empty.")
            return
        if not self.code_input.toPlainText(): # Allow empty description/category
            QMessageBox.warning(self, "Input Error", "Snippet Code cannot be empty.")
            return
        super().accept()


# --- Snippet Manager Pane Widget ---
class SnippetManagerPane(QWidget):
    """The widget for the snippet manager pane/dock."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.config_path = Path("config/snippets.json") # Store snippets in config
        self.snippets = {} # {category: [list_of_snippet_dicts]}
        self.categories = set() # Keep track of categories for the edit dialog

        self._init_ui()
        self._load_snippets()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # --- Toolbar ---
        toolbar = QToolBar("Snippet Actions")
        toolbar.setIconSize(QtCore.QSize(18, 18)) # Smaller icons

        add_action = QAction(QIcon.fromTheme("list-add"), "Add Snippet", self)
        add_action.triggered.connect(self._add_snippet)
        toolbar.addAction(add_action)

        self.edit_action = QAction(QIcon.fromTheme("document-edit"), "Edit Snippet", self)
        self.edit_action.triggered.connect(self._edit_snippet)
        self.edit_action.setEnabled(False)
        toolbar.addAction(self.edit_action)

        self.delete_action = QAction(QIcon.fromTheme("list-remove"), "Delete Snippet", self)
        self.delete_action.triggered.connect(self._delete_snippet)
        self.delete_action.setEnabled(False)
        toolbar.addAction(self.delete_action)

        toolbar.addSeparator()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search snippets...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_snippets)
        toolbar.addWidget(self.search_input)

        layout.addWidget(toolbar)

        # --- Tree/List and Preview Splitter ---
        splitter = QSplitter(Qt.Vertical)

        # Snippet Tree
        self.snippet_tree = QTreeWidget()
        self.snippet_tree.setHeaderLabel("Snippets")
        self.snippet_tree.setColumnCount(1)
        self.snippet_tree.currentItemChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.snippet_tree)

        # Preview Area
        preview_group = QGroupBox("Code Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(4, 8, 4, 4) # Adjust margins
        self.code_preview = QPlainTextEdit()
        self.code_preview.setReadOnly(True)
        self.code_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        code_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        code_font.setPointSize(9) # Slightly smaller font for preview
        self.code_preview.setFont(code_font)
        if HIGHLIGHTER_AVAILABLE:
            try:
                self.preview_highlighter = PythonHighlighter(self.code_preview.document())
            except Exception as e:
                 logger.warning(f"Could not apply highlighter to snippet preview: {e}")

        preview_layout.addWidget(self.code_preview)

        # Insert Button
        self.insert_button = QPushButton("Insert into Editor")
        self.insert_button.setIcon(QIcon.fromTheme("edit-paste"))
        self.insert_button.setEnabled(False)
        self.insert_button.clicked.connect(self._insert_snippet)
        preview_layout.addWidget(self.insert_button)

        splitter.addWidget(preview_group)
        splitter.setSizes([300, 200]) # Initial sizes

        layout.addWidget(splitter)

    def _load_snippets(self):
        """Load snippets from JSON file."""
        self.snippets = {} # Reset
        self.categories = set()
        loaded_snippets = []

        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_snippets = json.load(f)
                if not isinstance(loaded_snippets, list):
                     logger.error(f"Invalid format in {self.config_path}, expected a list. Resetting.")
                     loaded_snippets = []
            except json.JSONDecodeError:
                 logger.error(f"Error decoding JSON from {self.config_path}. Starting fresh or using defaults.")
                 # Optionally try loading defaults or just start empty
                 loaded_snippets = DEFAULT_SNIPPETS # Load defaults if file is corrupt
            except Exception as e:
                logger.exception(f"Failed to load snippets from {self.config_path}:")
                # Decide whether to load defaults or start empty
                loaded_snippets = DEFAULT_SNIPPETS # Load defaults on general error

        # If file didn't exist or load failed and defaults weren't loaded
        if not loaded_snippets and not self.config_path.exists():
             logger.info("Snippets file not found. Loading default snippets.")
             loaded_snippets = DEFAULT_SNIPPETS
             self._save_snippets() # Save defaults immediately if creating new

        # Organize loaded snippets by category
        for snippet in loaded_snippets:
            category = snippet.get("category", "General")
            self.categories.add(category)
            if category not in self.snippets:
                self.snippets[category] = []
            # Ensure basic structure
            if "id" in snippet and "name" in snippet and "code" in snippet:
                 self.snippets[category].append(snippet)
            else:
                 logger.warning(f"Skipping invalid snippet data: {snippet}")


        self._populate_tree()
        logger.info(f"Loaded {sum(len(v) for v in self.snippets.values())} snippets in {len(self.snippets)} categories.")

    def _save_snippets(self):
        """Save current snippets back to JSON file."""
        all_snippets_list = []
        # Flatten the dictionary back into a list for saving
        for category_list in self.snippets.values():
            all_snippets_list.extend(category_list)

        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(all_snippets_list, f, indent=2)
            logger.debug(f"Saved {len(all_snippets_list)} snippets to {self.config_path}")
        except Exception as e:
            logger.exception(f"Error saving snippets to {self.config_path}:")
            QMessageBox.critical(self, "Save Error", f"Could not save snippets:\n{e}")

    def _populate_tree(self, search_term=""):
        """Populate the tree widget with snippets, optionally filtered."""
        self.snippet_tree.clear()
        self.snippet_tree.setHeaderHidden(True) # Hide the header "Snippets"
        search_term = search_term.lower()
        found_items = False

        for category in sorted(self.snippets.keys()):
            snippets_in_category = self.snippets[category]

            # Filter snippets within the category
            filtered_snippets = []
            if search_term:
                 for snippet in snippets_in_category:
                      if (search_term in snippet['name'].lower() or
                          search_term in snippet.get('description','').lower() or
                          search_term in snippet['code'].lower() or
                          search_term in category.lower()):
                           filtered_snippets.append(snippet)
            else:
                 filtered_snippets = snippets_in_category # Show all if no search term

            if not filtered_snippets:
                 continue # Skip category if no matching snippets

            # Create category node
            category_item = QTreeWidgetItem(self.snippet_tree, [category])
            category_item.setFlags(category_item.flags() & ~Qt.ItemIsSelectable) # Make category non-selectable
            font = category_item.font(0)
            font.setBold(True)
            category_item.setFont(0, font)
            category_item.setForeground(0, QColor("#555599")) # Category color
            # No need to add category_item to tree here, happens automatically via parent arg

            # Add snippets under category
            for snippet in sorted(filtered_snippets, key=lambda x: x['name']):
                 # Parent is category_item
                 snippet_item = QTreeWidgetItem(category_item, [snippet['name']])
                 snippet_item.setData(0, Qt.UserRole, snippet) # Store full data
                 snippet_item.setToolTip(0, snippet.get('description', ''))
                 found_items = True

            category_item.setExpanded(True) # Keep categories expanded

        if not found_items and search_term:
             # *** FIX: Use addTopLevelItem for QTreeWidget ***
             no_match_item = QTreeWidgetItem(["No snippets match search."])
             no_match_item.setFlags(Qt.ItemFlag.NoItemFlags) # Make it non-selectable
             no_match_item.setForeground(0, Qt.GlobalColor.gray) # Make it gray
             self.snippet_tree.addTopLevelItem(no_match_item)
             # *** END FIX ***

        self._on_selection_changed(None, None) # Update preview/buttons


    @Slot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_selection_changed(self, current_item, previous_item):
        """Update preview and button states when selection changes."""
        snippet_data = None
        is_editable = False # Can edit/delete/insert?

        if current_item and current_item.parent(): # Check if it's a snippet item (has a parent category)
            snippet_data = current_item.data(0, Qt.UserRole)
            is_editable = True

        if snippet_data:
            self.code_preview.setPlainText(snippet_data.get("code", ""))
        else:
            self.code_preview.clear()

        self.edit_action.setEnabled(is_editable)
        self.delete_action.setEnabled(is_editable)
        self.insert_button.setEnabled(is_editable)

    @Slot()
    def _add_snippet(self):
        """Show dialog to add a new snippet."""
        dialog = SnippetEditDialog(existing_categories=self.categories, parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_snippet_data()
            category = new_data["category"]
            # Add category if it's new
            self.categories.add(category)
            if category not in self.snippets:
                self.snippets[category] = []
            # Add the snippet
            self.snippets[category].append(new_data)
            self._save_snippets()
            self._populate_tree(self.search_input.text()) # Refresh tree with filter
            logger.info(f"Added new snippet: {new_data['name']}")

    @Slot()
    def _edit_snippet(self):
        """Show dialog to edit the selected snippet."""
        current_item = self.snippet_tree.currentItem()
        if not current_item or not current_item.parent(): return # Must be a snippet item

        snippet_data = current_item.data(0, Qt.UserRole)
        if not snippet_data: return

        dialog = SnippetEditDialog(snippet_data, self.categories, self)
        if dialog.exec() == QDialog.Accepted:
            edited_data = dialog.get_snippet_data()
            original_category = snippet_data["category"]
            new_category = edited_data["category"]

            # Remove from old category list
            self.snippets[original_category] = [s for s in self.snippets[original_category] if s['id'] != edited_data['id']]
            # Remove old category if empty
            if not self.snippets[original_category]:
                 del self.snippets[original_category]
                 self.categories.discard(original_category)


            # Add to new category list
            self.categories.add(new_category)
            if new_category not in self.snippets:
                self.snippets[new_category] = []
            self.snippets[new_category].append(edited_data)

            self._save_snippets()
            self._populate_tree(self.search_input.text()) # Refresh tree with filter
            logger.info(f"Edited snippet: {edited_data['name']}")

    @Slot()
    def _delete_snippet(self):
        """Delete the selected snippet after confirmation."""
        current_item = self.snippet_tree.currentItem()
        if not current_item or not current_item.parent(): return

        snippet_data = current_item.data(0, Qt.UserRole)
        if not snippet_data: return

        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete the snippet '{snippet_data['name']}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            category = snippet_data["category"]
            snippet_id = snippet_data["id"]
            # Remove from category list
            self.snippets[category] = [s for s in self.snippets[category] if s['id'] != snippet_id]
            # Remove category if empty
            if not self.snippets[category]:
                 del self.snippets[category]
                 self.categories.discard(category)

            self._save_snippets()
            self._populate_tree(self.search_input.text()) # Refresh tree
            logger.info(f"Deleted snippet: {snippet_data['name']}")

    @Slot()
    def _insert_snippet(self):
        """Insert the selected snippet's code into the main editor."""
        current_item = self.snippet_tree.currentItem()
        if not current_item or not current_item.parent(): return

        snippet_data = current_item.data(0, Qt.UserRole)
        if not snippet_data or not snippet_data.get("code"): return

        code_to_insert = snippet_data["code"]

        # --- Get Editor ---
        if not hasattr(self.main_window, 'code_editor'):
            logger.error("Snippet Manager: Main window does not have 'code_editor' attribute.")
            QMessageBox.critical(self, "Error", "Cannot find code editor.")
            return

        editor = self.main_window.code_editor
        editor_tab = getattr(self.main_window, 'editor_tab', None)
        tab_widget = getattr(self.main_window, 'tab_widget', None)

        # --- Activate Editor ---
        if editor_tab and tab_widget:
            tab_widget.setCurrentWidget(editor_tab)
        if not editor.isEnabled() or editor.isReadOnly():
             logger.warning("Snippet Manager: Editor not enabled or is read-only.")
             QMessageBox.warning(self, "Editor Not Ready", "The code editor is not currently active or writable.")
             return

        # --- Insert Code ---
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.insertText(code_to_insert)
        logger.info(f"Inserted snippet: {snippet_data['name']}")


    @Slot(str)
    def _filter_snippets(self, text):
        """Filters the tree based on search text."""
        self._populate_tree(text)


# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Spider Snippet Manager plugin. Adds a dockable pane for managing code snippets.
    """
    def __init__(self):
        super().__init__()
        self.name = "Spider Snippet Manager"
        self.description = "Manage and insert reusable Scrapy code snippets."
        self.version = "1.0.0"
        self.main_window = None
        self.snippet_dock_widget = None
        self.snippet_pane = None # Add attribute for the pane itself

    def initialize_ui(self, main_window):
        """Create the Snippet Manager dock widget and add it."""
        self.main_window = main_window
        logger.info(f"Initializing UI for {self.name}...")

        # --- Essential Checks ---
        if not hasattr(main_window, 'addDockWidget'):
            logger.error(f"{self.name}: MainWindow does not support addDockWidget. Cannot add pane.")
            return
        if not hasattr(main_window, 'menuBar'):
            logger.warning(f"{self.name}: MainWindow missing menuBar. Cannot add View menu item.")
            # We can still proceed without the menu item if needed

        # --- Create Dock Widget ---
        try:
            self.snippet_dock_widget = QDockWidget("Code Snippets", main_window) # Parent to main window
            self.snippet_dock_widget.setObjectName("SnippetManagerDock")
            self.snippet_dock_widget.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea) # Allow left/right docking
            logger.debug(f"{self.name}: QDockWidget created.")

            # --- Create the Content Pane ---
            # Parent the pane widget *to the dock widget*
            self.snippet_pane = SnippetManagerPane(main_window, parent=self.snippet_dock_widget)
            logger.debug(f"{self.name}: SnippetManagerPane content widget created.")

            # --- Set Content Widget for the Dock ---
            self.snippet_dock_widget.setWidget(self.snippet_pane)
            logger.debug(f"{self.name}: Content pane set as widget for the dock.")

            # --- Add Dock Widget to Main Window ---
            # Add it to the right side initially
            main_window.addDockWidget(Qt.RightDockWidgetArea, self.snippet_dock_widget)
            logger.info(f"{self.name}: Dock widget added to the main window's right area.")

            # --- Add Menu Item to Show/Hide Dock ---
            if hasattr(main_window, 'menuBar'):
                menubar = main_window.menuBar()
                view_menu = None
                # Find existing 'View' menu or create one
                for action in menubar.actions():
                    menu = action.menu()
                    # More robust check for View menu
                    if menu and action.text().strip().replace('&', '').lower() == "view":
                        view_menu = menu
                        break
                if not view_menu:
                     view_menu = menubar.addMenu("&View")
                     logger.info(f"{self.name}: Created View menu.")


                # Use the dock widget's built-in toggle action
                toggle_dock_action = self.snippet_dock_widget.toggleViewAction()
                toggle_dock_action.setText("Snippet Pane") # Keep text concise
                toggle_dock_action.setIcon(QIcon.fromTheme("document-edit-symbolic", QIcon())) # Set icon if available
                toggle_dock_action.setToolTip("Show/Hide the Code Snippets Pane")

                # Insert after a separator if possible, otherwise append
                view_menu.addSeparator()
                view_menu.addAction(toggle_dock_action)
                logger.info(f"{self.name}: Added 'Snippet Pane' toggle action to View menu.")
            else:
                logger.warning(f"{self.name}: Could not add toggle action as menuBar is missing.")

        except Exception as e:
            logger.exception(f"Error during {self.name} UI initialization:")
            QMessageBox.critical(self.main_window, "Plugin Error", f"Failed to initialize {self.name}:\n{e}")
            # Clean up partially created widgets if error occurs
            if self.snippet_dock_widget:
                self.snippet_dock_widget.deleteLater()
                self.snippet_dock_widget = None
            self.snippet_pane = None

    def on_app_exit(self):
        """Save snippets on exit."""
        # Check if snippet_pane exists and has the method before calling
        if hasattr(self, 'snippet_pane') and self.snippet_pane and hasattr(self.snippet_pane, '_save_snippets'):
            logger.info(f"{self.name}: Saving snippets on exit...")
            self.snippet_pane._save_snippets()
        logger.info(f"{self.name} plugin exiting.")