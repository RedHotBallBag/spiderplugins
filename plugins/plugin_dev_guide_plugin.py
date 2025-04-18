import logging
import sys
from pathlib import Path

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView # Or QTextBrowser if no external links needed

# Import Plugin Base
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Tutorial Content (HTML String) ---
# This is where the bulk of the tutorial content goes.
# Using triple quotes allows multi-line strings easily.
TUTORIAL_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset='utf-8'>
    <title>Plugin Development Guide</title>
    <style>
        body {
            font-family: sans-serif;
            line-height: 1.6;
            padding: 15px;
            /* Basic theme adaptation (can be enhanced by Theme Switcher) */
            background-color: #fdfdfd;
            color: #333;
        }
        /* Dark theme adjustments (add more specific selectors if needed) */
        body.dark-theme {
             background-color: #2b2b2b;
             color: #ddd;
        }
        body.dark-theme h1, body.dark-theme h2, body.dark-theme h3 { color: #6cbafa; }
        body.dark-theme a { color: #8ab4f8; }
        body.dark-theme code { background-color: #444; color: #eee; }
        body.dark-theme pre { background-color: #363636; border: 1px solid #555; }
        body.dark-theme .note { background-color: #404040; border-left-color: #555; }
        body.dark-theme .warning { background-color: #5c4033; border-left-color: #8b4513; }
        body.dark-theme .code-example { background-color: #3a3a3a; border-color: #555; }


        h1 {
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }
        h2 {
            color: #3498db;
            margin-top: 30px;
            border-bottom: 1px solid #eee;
            padding-bottom: 3px;
        }
         body.dark-theme h2 { border-bottom-color: #555; }

        h3 {
            color: #2980b9;
            margin-top: 20px;
        }
        code {
            background-color: #f0f0f0;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: Consolas, monospace;
            font-size: 0.95em;
        }
        pre {
            background-color: #f8f8f8;
            padding: 12px;
            border-radius: 4px;
            overflow-x: auto;
            border: 1px solid #ddd;
            font-family: Consolas, monospace;
            font-size: 0.9em;
            margin: 10px 0;
        }
        ul { padding-left: 20px; }
        li { margin-bottom: 5px; }
        a { color: #3498db; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .note {
            background-color: #e8f4f8;
            padding: 10px 15px;
            border-left: 4px solid #3498db;
            margin: 20px 0;
            font-size: 0.95em;
        }
         .warning {
            background-color: #fff3cd;
            padding: 10px 15px;
            border-left: 4px solid #ffc107;
            margin: 20px 0;
            font-size: 0.95em;
        }
        .code-example {
             background-color: #f5f5f5;
             border: 1px solid #ccc;
             padding: 10px;
             margin-top: 5px;
             border-radius: 3px;
        }
        .toc {
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 25px;
        }
         body.dark-theme .toc { background-color: #383838; }
         .toc ul { list-style: none; padding-left: 0; }
         .toc li a { font-weight: bold; }

    </style>
</head>
<body>

    <h1>Plugin Development Guide</h1>

    <p>Welcome to the guide for creating plugins for the Scrapy Spider Manager!</p>

    <div class="toc">
        <strong>Table of Contents</strong>
        <ul>
            <li><a href="#introduction">1. Introduction</a></li>
            <li><a href="#plugin-structure">2. Plugin Structure</a></li>
            <li><a href="#plugin-base">3. The PluginBase Class</a></li>
            <li><a href="#lifecycle">4. Plugin Lifecycle & Hooks</a></li>
            <li><a href="#ui-integration">5. UI Integration</a>
                <ul>
                    <li><a href="#adding-menus">5.1 Adding Menu Items</a></li>
                    <li><a href="#adding-tabs">5.2 Adding Main Tabs</a></li>
                    <li><a href="#preferences">5.3 Adding Preference Panes</a></li>
                </ul>
            </li>
            <li><a href="#interacting">6. Interacting with the Application</a></li>
            <li><a href="#dependencies">7. Handling Dependencies</a></li>
            <li><a href="#best-practices">8. Best Practices</a></li>
            <li><a href="#examples">9. Examples</a></li>
        </ul>
    </div>


    <h2 id="introduction">1. Introduction</h2>
    <p>Plugins allow you to extend the functionality of the Scrapy Spider Manager. You can add new UI elements, interact with spider runs, process data, integrate external tools, and much more.</p>
    <p>Plugins are simple Python files (<code>.py</code>) placed in the application's <code>plugins/</code> directory. The application automatically discovers and loads them on startup.</p>

    <h2 id="plugin-structure">2. Plugin Structure</h2>
    <p>A basic plugin is a Python file containing a class named <code>Plugin</code> that inherits from <code>app.plugin_base.PluginBase</code>.</p>

    <div class="code-example">
    <strong>Example: <code>plugins/my_simple_plugin.py</code></strong>
    <pre><code class="language-python">
import logging
from app.plugin_base import PluginBase
from PySide6 import QtWidgets # If using UI elements

logger = logging.getLogger(__name__)

class Plugin(PluginBase):
    def __init__(self):
        super().__init__()
        # --- Required Metadata ---
        self.name = "My Simple Plugin" # User-visible name
        self.description = "A brief description of what this plugin does."
        self.version = "1.0.0" # Follow semantic versioning if possible

        # --- Plugin State (Optional) ---
        self.main_window = None # Will be set during initialization

    def initialize(self, main_window, config=None):
        \"\"\"Called once when the plugin is loaded after the main UI exists.\"\"\"
        self.main_window = main_window
        logger.info(f"{self.name} initialized.")
        # Load config if provided (from plugins/{plugin_name}.json)
        if config:
             self.config.update(config)
             logger.info(f"Loaded config for {self.name}")

        # Optional: Call UI setup if needed
        self.initialize_ui(main_window)

    def initialize_ui(self, main_window):
        \"\"\"Optional: Called by initialize if it exists. Setup UI elements here.\"\"\"
        # Example: Add a menu item (see UI Integration section)
        logger.info(f"{self.name} UI initialized.")
        pass # Replace with your UI setup

    def on_app_exit(self):
        \"\"\"Optional: Called when the application is closing. Clean up resources.\"\"\"
        logger.info(f"{self.name} exiting.")
        # Example: Stop background threads, close files, etc.

    # --- Other Optional Hook Methods (See Lifecycle section) ---

    </code></pre>
    </div>

    <h2 id="plugin-base">3. The PluginBase Class</h2>
    <p>Your plugin's <code>Plugin</code> class **must** inherit from <code>app.plugin_base.PluginBase</code>. This base class provides:</p>
    <ul>
        <li>Standard attributes: <code>name</code>, <code>description</code>, <code>version</code>, <code>main_window</code>, <code>config</code>.</li>
        <li>A default <code>initialize</code> method (you can override it).</li>
        <li>Definitions for optional hook methods (like <code>on_spider_started</code>).</li>
    </ul>
    <p>You should set at least <code>self.name</code>, <code>self.description</code>, and <code>self.version</code> in your plugin's <code>__init__</code>.</p>

    <h2 id="lifecycle">4. Plugin Lifecycle & Hooks</h2>
    <p>The application manages the plugin lifecycle:</p>
    <ol>
        <li><strong>Load:</strong> Plugin file is found in <code>plugins/</code> directory and imported. The <code>Plugin</code> class is instantiated (<code>__init__</code> runs).</li>
        <li><strong>Initialize:</strong> After the main application window is ready, the Plugin Manager calls <code>plugin.initialize(main_window, config)</code> on each loaded plugin instance. This is where you get the `main_window` reference. If `initialize_ui` exists, `initialize` calls it.</li>
        <li><strong>Event Hooks (Optional):</strong> Throughout the application's runtime, the Plugin Manager calls specific hook methods on your plugin instance if they are defined:
            <ul>
                <li><code>on_spider_started(self, spider_info)</code>: Called when a spider run begins via the `SpiderController`. `spider_info` is a dictionary containing details about the run (run_id, name, path, args, etc.).</li>
                <li><code>on_spider_finished(self, spider_info, status, item_count)</code>: Called when a spider run completes or is stopped. Includes the final `status` string and the calculated `item_count`.</li>
                <li><code>process_item(self, item)</code>: (Advanced) If implemented, this method is called by the Plugin Manager for *every* item yielded by *any* spider. It allows modifying items sequentially through plugins. **Use with caution**, performance-intensive. Must return the processed item.</li>
                <li><code>process_output(self, output)</code>: (Advanced) Called after a spider finishes, receives the *entire list* of items (if collected). Less common than `process_item` or pipelines. Must return the processed list.</li>
            </ul>
        </li>
        <li><strong>Exit:</strong> When the application closes, <code>plugin.on_app_exit()</code> is called, allowing for cleanup.</li>
    </ol>

    <h2 id="ui-integration">5. UI Integration</h2>
    <p>Plugins can add functionality to the main UI. Always do this within the <code>initialize_ui</code> method, as the `main_window` is guaranteed to exist then.</p>

    <h3 id="adding-menus">5.1 Adding Menu Items</h3>
    <p>You can add actions to existing menus (File, Edit, Tools, Help) or create new top-level menus.</p>
    <div class="code-example">
    <strong>Example: Adding to Tools Menu</strong>
    <pre><code class="language-python">
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMessageBox

# Inside your Plugin class...

def initialize_ui(self, main_window):
    self.main_window = main_window # Store reference if needed later

    if not hasattr(main_window, 'menuBar'):
        logger.error("Cannot add menu item: MainWindow missing menuBar.")
        return

    menubar = main_window.menuBar()
    tools_menu = None

    # Find existing "Tools" menu
    for action in menubar.actions():
        menu = action.menu()
        # Robust check: strip '&', compare lower case
        if menu and action.text().strip().replace('&','').lower() == "tools":
            tools_menu = menu
            break

    if not tools_menu:
        # Optionally create if it doesn't exist (might change menu order)
        # tools_menu = menubar.addMenu("&Tools")
        logger.warning("Could not find Tools menu to add action.")
        return # Or handle differently

    # Create your action
    my_action = QAction(QIcon.fromTheme("system-run"), "Run My Tool", main_window)
    my_action.setToolTip("Tooltip explaining the tool.")
    my_action.triggered.connect(self.run_my_tool_slot) # Connect to a slot method

    # Add action to the menu
    tools_menu.addAction(my_action)
    logger.info("Added 'Run My Tool' action to Tools menu.")

@Slot() # Decorator for PySide slots
def run_my_tool_slot(self):
    # This method is called when the menu item is clicked
    logger.info("My Tool action triggered!")
    QMessageBox.information(self.main_window, "My Plugin", "My tool was executed!")
    # Access main_window components here if needed (carefully)
    # e.g., project = self.main_window.current_project

    </code></pre>
    </div>

    <h3 id="adding-tabs">5.2 Adding Main Tabs</h3>
    <p>Create a custom `QWidget` for your tab's content and add it to the main `QTabWidget`.</p>
     <div class="code-example">
    <strong>Example: Adding a Custom Tab</strong>
    <pre><code class="language-python">
from PySide6 import QtWidgets

# Define your custom widget (can be in the same file or imported)
class MyPluginTabWidget(QtWidgets.QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel("Content for My Plugin Tab!")
        layout.addWidget(label)
        # Add more widgets here...

# Inside your Plugin class...
def initialize_ui(self, main_window):
    if not hasattr(main_window, 'tab_widget'):
         logger.error("Cannot add tab: MainWindow missing tab_widget.")
         return

    # Create instance of your custom widget
    self.my_tab = MyPluginTabWidget(main_window)

    # Add it to the main tab widget
    icon = QIcon.fromTheme("preferences-other") # Example icon
    main_window.tab_widget.addTab(self.my_tab, icon, "My Tab") # Set Icon and Title
    logger.info("Added 'My Tab' to the main window.")

    </code></pre>
    </div>

    <h3 id="preferences">5.3 Adding Preference Panes</h3>
    <p>The standard way is to create a settings widget and let the main Preferences dialog display it. The Notifier plugin is a good example.</p>
    <ol>
        <li>Create a method like `_create_settings_widget()` in your plugin that returns a `QWidget` (often a `QGroupBox`) containing your settings controls.</li>
        <li>In `initialize_ui`, add this widget to a dictionary on the `main_window` (e.g., `main_window.plugin_settings_widgets[self.name] = self._create_settings_widget()`).</li>
        <li>The `MainWindow._show_preferences` method needs to iterate through `main_window.plugin_settings_widgets` and add each widget to its preferences dialog (e.g., in separate tabs).</li>
        <li>Handle loading/saving settings within your plugin (using `self.config` or a dedicated JSON file).</li>
    </ol>


    <h2 id="interacting">6. Interacting with the Application</h2>
    <p>Your plugin gets a reference to the `main_window` object during initialization. You can use this to access public attributes and methods of the main window and its components (controllers, UI widgets).</p>
    <div class="warning">
        <strong>Warning:</strong> Direct access can create tight coupling. Relying on documented attributes/methods or signals/slots emitted by the main application (if available) is generally safer and more maintainable. Avoid accessing private attributes (those starting with `_` or `__`) unless absolutely necessary.
    </div>

    <div class="code-example">
    <strong>Example: Accessing Current Project & Running Spider</strong>
    <pre><code class="language-python">
# Inside your Plugin class...

def some_plugin_method(self):
    if not self.main_window:
        logger.error("Main window reference not available.")
        return

    # Access Project Controller (assuming it's self.main_window.project_controller)
    if hasattr(self.main_window, 'project_controller'):
        current_project = self.main_window.current_project # Get the currently selected project dict
        if current_project:
            project_name = current_project.get('name')
            project_path = current_project.get('path')
            logger.info(f"Current project: {project_name} at {project_path}")

            # Get spiders for this project
            spiders = self.main_window.project_controller.get_project_spiders(project_name)
            logger.info(f"Spiders in project: {spiders}")
        else:
             logger.info("No project selected in main window.")

    # Triggering a spider run (use main window's method if possible)
    if hasattr(self.main_window, '_run_spider') and self.main_window.current_project and self.main_window.current_spider:
         logger.info("Attempting to trigger run via MainWindow._run_spider")
         # Note: This assumes the MainWindow handles setting up args, output format etc.
         # It might be better if MainWindow had a higher-level `trigger_run(project, spider, args)` method.
         # Need to ensure the correct spider is selected in the main Spiders tab for _run_spider to work.
         # See SpiderDashboard plugin for an example of how to select the spider first.
         # self.main_window._run_spider() # This call needs care
    else:
        logger.warning("Cannot trigger run: Main window missing method or no project/spider selected.")


    # Accessing the Code Editor
    if hasattr(self.main_window, 'code_editor'):
        editor = self.main_window.code_editor
        current_text = editor.toPlainText()
        # editor.insertPlainText("Text from plugin!")
    </code></pre>
    </div>


    <h2 id="dependencies">7. Handling Dependencies</h2>
    <p>If your plugin requires external Python libraries (like `requests`, `pandas`, `flask`), you need to manage them.</p>
    <ul>
        <li>**Document:** Clearly state dependencies in your plugin's description or a separate `README`.</li>
        <li>**Check:** Use the `app.plugin_dependency_manager.ensure_package()` function within your `initialize_ui` or `initialize` method. This function currently *prompts* the user via the console to install missing packages, which is not ideal for a GUI app.</li>
        <li>**Better Approach:**
            <ol>
                <li>Modify `ensure_package` to simply `return False` if the import fails, without prompting.</li>
                <li>In your plugin's `initialize_ui`, call the modified `ensure_package`.</li>
                <li>If it returns `False`, log an error, **show a `QMessageBox`** telling the user which package is needed and how to install it (`pip install ...`), and then disable the plugin's functionality (e.g., disable its menu items or show a message on its tab).</li>
            </ol>
        </li>
        <li>**Plugin Store:** The store can list dependencies defined in the catalog JSON.</li>
    </ul>
     <div class="code-example">
    <strong>Example: Checking Dependency</strong>
    <pre><code class="language-python">
# At the top of your plugin file
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Inside initialize_ui...
def initialize_ui(self, main_window):
    self.main_window = main_window
    if not PANDAS_AVAILABLE:
        logger.error(f"{self.name} requires 'pandas'. Please install it (`pip install pandas`).")
        # Optional: Show message box to user ONCE (maybe check a flag)
        # QMessageBox.warning(main_window, "Dependency Missing", f"{self.name} requires 'pandas'. Functionality disabled.")
        # Disable UI elements related to pandas
        # e.g., self.my_pandas_button.setEnabled(False)
        return # Stop further UI initialization for this plugin

    # ... rest of your UI setup ...
    </code></pre>
    </div>


    <h2 id="best-practices">8. Best Practices</h2>
    <ul>
        <li><strong>Keep it Modular:**</strong> Try to keep your plugin focused on a specific task.</li>
        <li><strong>Error Handling:**</strong> Use `try...except` blocks for file operations, network requests, and interactions with potentially missing `main_window` components. Log errors clearly using `logger.error()` or `logger.exception()`.</li>
        <li><strong>GUI Responsiveness:**</strong> For long-running tasks (network requests, heavy processing, file I/O), use background threads (`QThread`, `threading`) or `asyncio` (if the main app supports it) to avoid freezing the UI. Use signals to communicate results back to the UI thread.</li>
        <li><strong>Configuration:**</strong> If your plugin needs settings, store them in a dedicated JSON file in the `config/` directory (e.g., `config/my_plugin_settings.json`) or integrate with the Preferences dialog. Avoid hardcoding values.</li>
        <li><strong>Logging:**</strong> Use the `logging` module (`logger = logging.getLogger(__name__)`) for informative messages (debug, info, warning, error).</li>
        <li><strong>Clean Up:**</strong> Implement `on_app_exit` if your plugin starts threads, opens files, or holds external resources that need explicit cleanup.</li>
    </ul>

    <h2 id="examples">9. Examples</h2>
    <p>Refer to the bundled plugins for practical examples:</p>
    <ul>
        <li><strong>`stats_statusbar_plugin.py`:** Simplest example using lifecycle hooks.</li>
        <li><strong>`open_project_folder_plugin.py`:** Example of adding a context menu item.</li>
        <li><strong>`plugin_store_plugin.py`:** Example of using QThread, network requests, file I/O, and a more complex dialog.</li>
        <li><strong>`theme_switcher_plugin.py`:** Example of modifying main window style and adding preferences.</li>
    </ul>

    <p>Happy Plugin Development!</p>

</body>
</html>
"""


# --- Plugin Widget ---
class PluginDevGuideWidget(QtWidgets.QWidget):
    """Displays the plugin development tutorial content."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0) # Use full space

        # Option 1: QTextBrowser (simpler, good for internal content)
        # self.text_browser = QtWidgets.QTextBrowser()
        # self.text_browser.setOpenExternalLinks(True) # Allow opening http links
        # self.text_browser.setHtml(TUTORIAL_HTML)
        # layout.addWidget(self.text_browser)

        # Option 2: QWebEngineView (more powerful, better CSS/JS support if needed)
        # Requires PySide6-WebEngine
        try:
            self.web_view = QWebEngineView()
            self.web_view.setHtml(TUTORIAL_HTML, baseUrl=QtCore.QUrl("qrc:/")) # Base URL might help relative links if any
            layout.addWidget(self.web_view)
        except ImportError:
             logger.error("QWebEngineView not available for Plugin Dev Guide. Falling back to QTextBrowser.")
             label = QtWidgets.QLabel("Error: PySide6-WebEngine is required to view this guide properly.")
             layout.addWidget(label)
        except Exception as e:
            logger.exception("Error initializing QWebEngineView for Plugin Dev Guide:")
            label = QtWidgets.QLabel(f"Error loading guide: {e}")
            layout.addWidget(label)

    # Add method to potentially update content based on theme changes if needed
    # def update_theme(self, theme_name):
    #     if hasattr(self, 'web_view'):
    #          js_code = f"document.body.className = '{theme_name}-theme';" # Example JS
    #          self.web_view.page().runJavaScript(js_code)
    #     elif hasattr(self, 'text_browser'):
    #          # QTextBrowser styling is harder to change dynamically for complex HTML
    #          pass


# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Plugin to add a 'Plugin Development Guide' tab.
    """
    def __init__(self):
        super().__init__()
        self.name = "Plugin Development Guide"
        self.description = "Provides documentation and examples for creating plugins."
        self.version = "1.0.0"
        self.main_window = None
        self.guide_tab = None

    def initialize_ui(self, main_window):
        """Create the Guide tab and add it to the main window."""
        self.main_window = main_window

        # Check for WebEngine dependency if using QWebEngineView
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            logger.warning(f"{self.name}: PySide6-WebEngine not found. Guide display might be limited.")
            # Allow initialization to continue with fallback if QTextBrowser is used

        if hasattr(main_window, 'tab_widget'):
            try:
                self.guide_tab = PluginDevGuideWidget(main_window)
                icon = QIcon.fromTheme("help-contents", QIcon.fromTheme("document-properties"))
                main_window.tab_widget.addTab(self.guide_tab, icon, "Plugin Dev Guide")
                logger.info(f"{self.name} plugin initialized UI.")
            except Exception as e:
                logger.exception(f"Failed to initialize {self.name} UI:")
                # Don't show critical message, just log error
        else:
            logger.error(f"Could not find main window's tab_widget to add {self.name} tab.")

    def on_app_exit(self):
        logger.info(f"{self.name} plugin exiting.")