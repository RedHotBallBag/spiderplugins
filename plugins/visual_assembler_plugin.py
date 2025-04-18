import logging


import sys


import json


from pathlib import Path





# Import necessary PySide6 components


from PySide6 import QtWidgets, QtCore, QtGui


from PySide6.QtGui import QAction, QIcon, QDrag, QPixmap


from PySide6.QtCore import Qt, Slot, QMimeData, QPoint





# Import Plugin Base


from app.plugin_base import PluginBase


# IMPORTANT: Need access to the main CodeEditor instance


# This might require modification in MainWindow or PluginManager initialization





logger = logging.getLogger(__name__)





# --- Define Snippets and MIME Type ---


MIME_TYPE_SCRAPY_SNIPPET = "application/x-scrapy-snippet-key"





# Dictionary: Key = Display Name, Value = { code_template, params: {name: type}, tooltip, mime_data }


# Param types: 'text', 'variable', 'callback_name' (determines dialog type)


SNIPPETS = {


    "Start Request": {


        "code": "\nyield scrapy.Request(url='{url}', callback=self.{callback_name})\n",


        "params": {"url": "text", "callback_name": "text"},


        "tooltip": "Generate a scrapy.Request to fetch a URL.",


        "icon": "network-transmit-receive" # Example theme icon name


    },


    "CSS Selector (Get First)": {


        "code": "{variable_name} = response.css('{selector}').get()",


        "params": {"variable_name": "text", "selector": "text"},


        "tooltip": "Select the first element using CSS selector.",


         "icon": "edit-select-all"


    },


    "CSS Selector (Get All)": {


        "code": "{variable_name} = response.css('{selector}').getall()",


        "params": {"variable_name": "text", "selector": "text"},


        "tooltip": "Select all elements using CSS selector.",


        "icon": "edit-select-all"


    },


    "XPath Selector (Get First)": {


        "code": "{variable_name} = response.xpath('{selector}').get()",


        "params": {"variable_name": "text", "selector": "text"},


        "tooltip": "Select the first element using XPath selector.",


        "icon": "edit-select-all" # Consider different icon maybe


    },


    "XPath Selector (Get All)": {


        "code": "{variable_name} = response.xpath('{selector}').getall()",


        "params": {"variable_name": "text", "selector": "text"},


        "tooltip": "Select all elements using XPath selector.",


         "icon": "edit-select-all"


    },


     "Loop Over Elements": {


        "code": "\nfor {loop_variable} in response.{method}('{selector}'):\n    # Process each {loop_variable} here\n    pass\n",


        "params": {"method": ["css", "xpath"], "selector": "text", "loop_variable": "text"}, # Special param type 'list'


        "tooltip": "Iterate over elements found by a selector.",


        "icon": "view-list-tree"


    },


    "Yield Item": {


        # Template encourages dictionary items first for simplicity


        "code": "\nyield {{\n    '{field1}': {value1},\n    '{field2}': {value2},\n    # Add more fields...\n}}\n",


        "params": {"field1": "text", "value1": "text", "field2": "text", "value2": "text"},


        "tooltip": "Yield a scraped data item (as a dictionary).",


        "icon": "document-export"


    },


    "Follow Link": {


        "code": "\nnext_page = response.{method}('{selector}').get()\nif next_page is not None:\n    yield response.follow(next_page, callback=self.{callback_name})\n",


        "params": {"method": ["css", "xpath"], "selector": "text", "callback_name": "text"},


        "tooltip": "Follow a link extracted by a selector.",


        "icon": "go-next"


    },


    "Get Attribute": {


         "code": "response.{method}('{selector}::attr({attribute_name})').get()",


         "params": {"method": ["css", "xpath"], "selector": "text", "attribute_name": "text"},


         "tooltip": "Extract an attribute value from an element.",


         "icon": "document-properties"


    },


    "Basic Item Class": {


        "code": "\nimport scrapy\n\nclass {item_class_name}(scrapy.Item):\n    # define the fields for your item here like:\n    {field1} = scrapy.Field()\n    {field2} = scrapy.Field()\n    pass\n",


        "params": {"item_class_name": "text", "field1": "text", "field2": "text"},


        "tooltip": "Define a basic Scrapy Item class structure.",


        "icon": "document-new"


    }


    # Add more snippets: Logging, Item Loaders, etc.


}





# --- Palette Widget ---


class SnippetPalette(QtWidgets.QListWidget):


    def __init__(self, parent=None):


        super().__init__(parent)


        self.setDragEnabled(True)


        self.setViewMode(QtWidgets.QListView.IconMode) # Or ListMode


        self.setFlow(QtWidgets.QListView.LeftToRight) # Arrange icons horizontally


        self.setWrapping(True) # Wrap items


        self.setSpacing(10)


        self.setIconSize(QtCore.QSize(48, 48)) # Adjust size as needed


        self.setAcceptDrops(False) # Palette doesn't accept drops


        self.setDropIndicatorShown(False)





        self._populate_list()





    def _populate_list(self):


        for name, data in SNIPPETS.items():


            item = QtWidgets.QListWidgetItem(name)


            item.setData(Qt.UserRole, name) # Store the snippet key


            item.setToolTip(data.get('tooltip', ''))


            # Set icon from theme


            icon_name = data.get('icon', 'text-x-generic') # Default icon


            item.setIcon(QIcon.fromTheme(icon_name))


            self.addItem(item)





    def startDrag(self, supportedActions):


        item = self.currentItem()


        if not item:


            return





        snippet_key = item.data(Qt.UserRole)


        if not snippet_key:


            return





        mime_data = QMimeData()


        # Encode the key as bytes for MIME data


        mime_data.setData(MIME_TYPE_SCRAPY_SNIPPET, snippet_key.encode('utf-8'))





        drag = QDrag(self)


        drag.setMimeData(mime_data)





        # Create a simple pixmap for drag visual


        pixmap = QPixmap(64, 64)


        pixmap.fill(Qt.transparent)


        painter = QtGui.QPainter(pixmap)


        icon_pixmap = item.icon().pixmap(48, 48)


        painter.drawPixmap(0, 0, icon_pixmap)


        painter.setPen(Qt.black)


        painter.drawText(QtCore.QRect(0, 48, 64, 16), Qt.AlignCenter, item.text()[:10]) # Draw text below icon


        painter.end()


        drag.setPixmap(pixmap)


        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))





        logger.debug(f"Starting drag for snippet: {snippet_key}")


        # Execute the drag operation


        drag.exec(supportedActions, Qt.CopyAction)





# --- Code Editor Modifications (Need to be applied to the main CodeEditor) ---


# We'll define the methods here, but they need to be added/monkey-patched


# onto the existing CodeEditor class instance during plugin initialization.





def code_editor_dragEnterEvent(self, event: QtGui.QDragEnterEvent):


    """Handles drag enter events for the code editor."""


    mime_data = event.mimeData()


    if mime_data.hasFormat(MIME_TYPE_SCRAPY_SNIPPET):


        event.acceptProposedAction()


        logger.debug("Snippet drag entered editor")


    else:


        # Important: Call the original dragEnterEvent if it exists


        # This allows default drag/drop behavior (like text) to work


        if hasattr(super(type(self), self), 'dragEnterEvent'):


             super(type(self), self).dragEnterEvent(event)


        else:


             event.ignore()








def code_editor_dragMoveEvent(self, event: QtGui.QDragMoveEvent):


    """Handles drag move events."""


    if event.mimeData().hasFormat(MIME_TYPE_SCRAPY_SNIPPET):


         # Optional: provide visual feedback or constraints


        event.acceptProposedAction()


    elif hasattr(super(type(self), self), 'dragMoveEvent'):


        super(type(self), self).dragMoveEvent(event)


    else:


        event.ignore()





def code_editor_dropEvent(self, event: QtGui.QDropEvent):


    """Handles the drop event."""


    mime_data = event.mimeData()


    if mime_data.hasFormat(MIME_TYPE_SCRAPY_SNIPPET):


        snippet_key_bytes = mime_data.data(MIME_TYPE_SCRAPY_SNIPPET)


        try:


            snippet_key = snippet_key_bytes.data().decode('utf-8') # Decode bytes


            logger.info(f"Dropped snippet: {snippet_key}")





            snippet_data = SNIPPETS.get(snippet_key)


            if snippet_data:


                # Get parameters from user


                params = self._get_snippet_params(snippet_data.get("params", {}))


                if params is None: # User cancelled


                     event.ignore()


                     return





                # Format the code snippet


                code_to_insert = snippet_data["code"].format(**params)





                 # --- Handle Variations (e.g., .get/.getall) ---


                if "Selector" in snippet_key:


                     menu = QtWidgets.QMenu(self)


                     get_action = menu.addAction(".get()")


                     getall_action = menu.addAction(".getall()")


                     no_method_action = menu.addAction("(no method)")





                     chosen_action = menu.exec(event.globalPosition().toPoint())





                     method_suffix = ""


                     if chosen_action == get_action:


                          method_suffix = ".get()"


                     elif chosen_action == getall_action:


                          method_suffix = ".getall()"


                     # If no_method_action or cancelled, suffix remains empty





                     # Insert the chosen variation


                     final_code = code_to_insert.replace('{method}', method_suffix) # Simple replace if template includes it


                     # Or append if the base template didn't have {method}


                     if '{method}' not in code_to_insert:


                          final_code += method_suffix





                     code_to_insert = final_code.strip() # Remove leading/trailing whitespace before inserting





                # Get cursor at drop position


                cursor = self.cursorForPosition(event.position().toPoint())


                self.setTextCursor(cursor)


                # Insert the formatted code


                self.insertPlainText(code_to_insert)


                self.setFocus()


                event.acceptProposedAction()


            else:


                logger.warning(f"Dropped snippet key '{snippet_key}' not found in SNIPPETS.")


                event.ignore()


        except Exception as e:


            logger.error(f"Error processing dropped snippet: {e}")


            event.ignore()


    elif hasattr(super(type(self), self), 'dropEvent'):


         # Allow default drop behavior (like dropping text files)


         super(type(self), self).dropEvent(event)


    else:


         event.ignore()








def code_editor_get_snippet_params(self, params_config):


    """Helper method to get parameters for a snippet using dialogs."""


    params = {}


    dialog_parent = self # Or self.window()





    for name, config in params_config.items():


        value = None


        ok = False





        if isinstance(config, list): # Special case for dropdown selection


             item, ok = QtWidgets.QInputDialog.getItem(dialog_parent, "Select Option", f"Choose for '{name}':", config, 0, editable=False)


             if ok and item:


                  value = item


        elif config == "text":


            # Add default values based on name for convenience


            default_text = ""


            if name == "variable_name": default_text = "data"


            elif name == "loop_variable": default_text = "element"


            elif name == "callback_name": default_text = "parse_item"


            elif name == "field1": default_text = "field_name_1"


            elif name == "field2": default_text = "field_name_2"


            elif name == "value1": default_text = "value_expr_1"


            elif name == "value2": default_text = "value_expr_2"


            elif name == "selector": default_text = "your_selector_here"


            elif name == "url": default_text = "https://example.com"


            elif name == "item_class_name": default_text = "MyItem"








            text, ok = QtWidgets.QInputDialog.getText(dialog_parent, "Enter Parameter", f"Value for '{name}':", text=default_text)


            if ok and text:


                value = text


        # Add more types like 'int', 'callback_name' (maybe dropdown of functions?) later





        if ok:


            params[name] = value


        else:


            logger.info("Snippet parameter input cancelled by user.")


            return None # User cancelled


    return params





# --- Main Plugin Widget ---


class VisualBuilderWidget(QtWidgets.QWidget):


    """Container widget for the visual builder tab."""


    def __init__(self, main_window, parent=None):


        super().__init__(parent)


        self.main_window = main_window





        layout = QtWidgets.QVBoxLayout(self)


        layout.setContentsMargins(5, 5, 5, 5)





        # Instructions


        instructions = QtWidgets.QLabel("<b>Visual Spider Assembler</b>: Drag actions from the palette below onto the main Code Editor tab.")


        instructions.setWordWrap(True)


        layout.addWidget(instructions)





        # Palette


        self.palette = SnippetPalette()


        layout.addWidget(self.palette)


        layout.addStretch()








# --- Plugin Class ---


class Plugin(PluginBase):


    """


    Plugin to add a Visual Spider Assembler tab.


    """


    def __init__(self):


        super().__init__()


        self.name = "Visual Spider Assembler"


        self.description = "Drag & drop Scrapy code snippets onto the editor."


        self.version = "1.1.0"


        self.main_window = None


        self.builder_widget = None


        self.original_editor_methods = {} # To store original methods if patching





    def initialize_ui(self, main_window):


        """Create the Assembler tab and modify the CodeEditor."""


        self.main_window = main_window





        if not hasattr(main_window, 'code_editor'):


             logger.error("Visual Assembler requires the main window to have a 'code_editor' attribute.")


             return # Cannot proceed without the editor





        # 1. Add the Tab


        if hasattr(main_window, 'tab_widget'):


            try:


                self.builder_widget = VisualBuilderWidget(main_window)


                icon = QIcon.fromTheme("insert-object", QIcon()) # Generic 'insert' icon


                main_window.tab_widget.addTab(self.builder_widget, icon, "Visual Assembler")


                logger.info("Visual Assembler plugin tab initialized.")


            except Exception as e:


                logger.exception("Failed to initialize Visual Assembler tab UI:")


                # Don't prevent editor modification attempt if tab fails


        else:


            logger.error("Could not find main window's tab_widget to add Assembler tab.")








        # 2. Modify CodeEditor for Drag & Drop


        editor = main_window.code_editor


        logger.info("Attempting to enable snippet drop on CodeEditor...")





        # Enable accepting drops


        editor.setAcceptDrops(True)





        # Monkey-patch the drag/drop methods onto the *instance*


        # Store original methods first in case we need to restore them


        methods_to_patch = {


            "dragEnterEvent": code_editor_dragEnterEvent,


            "dragMoveEvent": code_editor_dragMoveEvent,


            "dropEvent": code_editor_dropEvent,


            "_get_snippet_params": code_editor_get_snippet_params # Add helper


        }





        for name, func in methods_to_patch.items():


             # Store original if it exists and we haven't already patched it


             if hasattr(editor, name) and name not in self.original_editor_methods:


                  self.original_editor_methods[name] = getattr(editor, name)


             # Bind the new method to the instance


             setattr(editor, name, func.__get__(editor, type(editor)))


             logger.debug(f"Patched '{name}' method onto CodeEditor instance.")





        logger.info("CodeEditor modified for snippet drag and drop.")








    def on_app_exit(self):


        """Restore original editor methods if they were patched."""


        if self.main_window and hasattr(self.main_window, 'code_editor'):


            editor = self.main_window.code_editor


            for name, original_method in self.original_editor_methods.items():


                logger.debug(f"Restoring original '{name}' method on CodeEditor.")


                setattr(editor, name, original_method)


            # Disable drops again? Maybe not necessary if app is closing.


            # editor.setAcceptDrops(False)


        logger.info("Visual Assembler plugin exiting.")
