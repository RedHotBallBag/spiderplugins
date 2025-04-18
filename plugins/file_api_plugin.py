import logging
import sys
import os
import json
import threading
from pathlib import Path

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QDesktopServices
from PySide6.QtCore import Qt, Slot, QUrl
from PySide6.QtWidgets import QMessageBox

# Import Plugin Base
from app.plugin_base import PluginBase

# --- Check for Flask Dependency ---
try:
    from flask import Flask, jsonify, request, abort, Response
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logging.warning("File API Plugin: 'Flask' library not found. Please install it (`pip install Flask`). API features will be disabled.")

logger = logging.getLogger(__name__)

# --- Configuration ---
API_HOST = "127.0.0.1" # Listen only on localhost for security by default
API_PORT = 5151       # Choose a relatively uncommon port

# Global variable to hold the Flask app instance (needed for thread access)
# Note: A class-based approach might be cleaner for larger APIs
flask_app = None
server_thread = None
main_app_window = None # Reference to the main window

# --- Flask Routes ---
# These functions define the API logic. They need access to main_app_window.

def setup_flask_routes(app, main_window_ref):
    """Sets up the Flask routes, capturing the main window reference."""
    global main_app_window
    main_app_window = main_window_ref 

    @app.route('/api/projects', methods=['GET'])
    def get_projects():
        if not main_app_window or not hasattr(main_app_window, 'project_controller'):
            return jsonify({"error": "Project controller unavailable"}), 500
        try:
            projects = main_app_window.project_controller.get_projects()
            # Return only basic info, exclude full paths for potential security
            project_list = [
                {"name": name, "description": data.get("description", "")}
                for name, data in projects.items()
            ]
            return jsonify(project_list)
        except Exception as e:
            logger.error(f"Error getting projects: {e}", exc_info=True)
            return jsonify({"error": "Failed to retrieve projects"}), 500

    @app.route('/api/projects/<string:project_name>/files/', defaults={'sub_path': ''})
    @app.route('/api/projects/<string:project_name>/files/<path:sub_path>', methods=['GET'])
    def list_or_get_file(project_name, sub_path):
        # ... (checks for main_window and project_controller) ...

        projects = main_app_window.project_controller.get_projects()
        project_data = projects.get(project_name)

        if not project_data:
            abort(404, description=f"Project '{project_name}' not found.")

        # --- Correct Base Path Logic ---
        # The path stored is the outer dir (contains scrapy.cfg)
        outer_project_path = Path(project_data['path'])
        # The module path is usually the outer path + project name subdir
        # Ensure project_name is derived safely if needed, though it should match the key
        module_name = project_name # Assuming project dict key matches module name
        base_project_path = outer_project_path / module_name # <<< CHANGE: Point to inner module dir

        if not base_project_path.is_dir():
             # Fallback: Maybe project wasn't created with standard nesting? Check if files exist directly in outer path.
             # This handles cases where users might add projects created differently.
             if (outer_project_path / 'settings.py').exists():
                  logger.warning(f"Project '{project_name}' doesn't have standard module nesting. Using outer path as base.")
                  base_project_path = outer_project_path
             else:
                  logger.error(f"Could not find project module directory for '{project_name}' at '{base_project_path}' or standard files in '{outer_project_path}'.")
                  abort(500, description=f"Project module directory structure for '{project_name}' is invalid or inaccessible.")
        # --- End Base Path Logic ---


        # --- Security: Path Sanitization ---
        try:
            # Strip leading slashes/backslashes before joining
            safe_sub_path_str = sub_path.lstrip('/\\')
            # Ensure joining doesn't create invalid paths (e.g. empty components)
            path_parts = [part for part in Path(safe_sub_path_str).parts if part and part != '.']
            full_path = base_project_path.joinpath(*path_parts).resolve()
        except Exception as path_e:
             logger.warning(f"Invalid file path requested: {project_name}/{sub_path} -> {path_e}")
             abort(400, description="Invalid file path requested.")

        # Check if the resolved path is still within the corrected base project directory
        if not str(full_path).startswith(str(base_project_path.resolve())):
            logger.warning(f"Path traversal attempt blocked: {project_name}/{sub_path} (Resolved: {full_path}, Base: {base_project_path.resolve()})")
            abort(403, description="Access denied: Path is outside project module directory.")
        # --- End Security ---

        if not full_path.exists():
             abort(404, description=f"File or directory not found within project module: {sub_path if sub_path else '(root)'}")

        # --- Rest of the function (listing dir, reading file) remains the same ---
        if full_path.is_dir():
            try:
                items = []
                for item in sorted(full_path.iterdir()):
                    # Calculate path relative to the module base for the API response
                    relative_p = str(item.relative_to(base_project_path)).replace("\\", "/")
                    items.append({
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "path": relative_p
                    })
                # Return path relative to /files/ base
                api_path = str(Path(sub_path)).replace("\\", "/")
                return jsonify({"path": api_path, "contents": items})
            except OSError as e:
                 logger.error(f"Error listing directory {full_path}: {e}")
                 abort(500, description=f"Error listing directory contents.")

        elif full_path.is_file():
            try:
                content_type = 'text/plain; charset=utf-8'
                if full_path.suffix.lower() == '.json':
                    content_type = 'application/json; charset=utf-8'
                elif full_path.suffix.lower() == '.py':
                    content_type = 'text/x-python; charset=utf-8'
                elif full_path.suffix.lower() == '.html':
                    content_type = 'text/html; charset=utf-8'

                content = full_path.read_text(encoding='utf-8', errors='ignore')
                return Response(content, mimetype=content_type)
            except OSError as e:
                logger.error(f"Error reading file {full_path}: {e}")
                abort(500, description="Error reading file.")
            except Exception as e:
                 logger.exception(f"Unexpected error reading file {full_path}:")
                 abort(500, description="Unexpected error reading file.")
        else:
             abort(404, description="Path exists but is not a file or directory.")


# --- Flask Server Thread ---
def run_flask_server():
    """Target function for the Flask server thread."""
    global flask_app
    if not flask_app or not FLASK_AVAILABLE:
        logger.error("Flask app not initialized or Flask not available. Server thread exiting.")
        return
    try:
        logger.info(f"Starting Flask server on http://{API_HOST}:{API_PORT}")
        # Use Werkzeug's development server. Not for production!
        # Set use_reloader=False to prevent issues with threading and restarts.
        flask_app.run(host=API_HOST, port=API_PORT, debug=False, use_reloader=False)
        logger.info("Flask server thread finished.") # Will only be reached if server stops cleanly
    except OSError as e:
        logger.error(f"Flask server failed to start (Port {API_PORT} likely in use): {e}")
        # Optionally signal the main thread/UI about the failure
    except Exception:
        logger.exception("Flask server thread encountered an unexpected error.")

# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Plugin to run a local API server for project file access.
    """
    def __init__(self):
        super().__init__()
        self.name = "Project File API"
        self.description = "Runs a local API server (Flask) to view project files."
        self.version = "1.0.0"
        self.main_window = None
        self.server_running = False
        self.api_status_action = None

    def initialize_ui(self, main_window):
        """Initialize Flask app, setup routes, and start server thread."""
        global flask_app # Allow modifying the global app instance
        self.main_window = main_window

        if not FLASK_AVAILABLE:
            logger.error(f"{self.name} disabled: Flask library not found.")
            return # Cannot initialize UI without Flask

        if not hasattr(main_window, 'project_controller'):
             logger.error(f"{self.name} requires 'project_controller'. Plugin disabled.")
             return

        # Create Flask app instance
        if flask_app is None: # Avoid recreating if already exists (e.g., plugin reload)
             flask_app = Flask(f"{self.name}_App")
             setup_flask_routes(flask_app, self.main_window) # Pass main window ref
        else:
             logger.warning(f"{self.name}: Flask app already exists. Skipping route setup.")


        # Start Flask server in a background thread
        self._start_server_thread()

        # Add menu item to show status/URL
        self._add_menu_item()

        logger.info(f"{self.name} plugin initialized.")

    def _start_server_thread(self):
        global server_thread
        if server_thread is None or not server_thread.is_alive():
            server_thread = threading.Thread(target=run_flask_server, name="FlaskAPIServerThread", daemon=True)
            server_thread.start()
            self.server_running = True # Assume it starts successfully for now
            # TODO: Add mechanism to confirm server actually bound the port
        else:
            logger.warning(f"{self.name}: Server thread already running.")


    def _add_menu_item(self):
         """Adds an item to the Tools menu."""
         if not hasattr(self.main_window, 'menuBar'): return

         menubar = self.main_window.menuBar()
         tools_menu_action = None
         for action in menubar.actions():
            if action.menu() and action.text().strip().replace('&','').lower() == "tools":
                tools_menu_action = action
                break
         if not tools_menu_action: return
         tools_menu = tools_menu_action.menu()
         if not tools_menu: return

         # Remove previous action if it exists (e.g., on reload)
         if self.api_status_action:
              tools_menu.removeAction(self.api_status_action)

         status_text = f"File API Status: Running at http://{API_HOST}:{API_PORT}" if self.server_running else "File API Status: Not Running"
         self.api_status_action = QAction(status_text, self.main_window)
         self.api_status_action.setToolTip("Click to view API base URL (opens browser)")
         self.api_status_action.triggered.connect(self._show_api_info)
         self.api_status_action.setEnabled(self.server_running) # Only enable if running
         tools_menu.addAction(self.api_status_action)


    @Slot()
    def _show_api_info(self):
        """Shows info about the running API."""
        if self.server_running:
            api_url = f"http://{API_HOST}:{API_PORT}/api/projects"
            msg = (f"The Project File API is running.\n\n"
                   f"Base URL: http://{API_HOST}:{API_PORT}\n\n"
                   f"Example: Listing projects at:\n{api_url}\n\n"
                   f"(Only accessible from this computer by default)")
            # Open example URL in browser?
            reply = QMessageBox.information(
                self.main_window,
                f"{self.name} Status",
                msg,
                QMessageBox.Ok | QMessageBox.Open, # Add Open button
                QMessageBox.Ok
                )
            if reply == QMessageBox.Open:
                 QDesktopServices.openUrl(QUrl(api_url))

        else:
            QMessageBox.warning(
                self.main_window,
                f"{self.name} Status",
                "The API server is not currently running or failed to start.\nCheck application logs for details."
            )


    def on_app_exit(self):
        """Attempt to signal server shutdown (though daemon thread might just exit)."""
        global server_thread
        logger.info(f"{self.name} plugin exiting. Flask server thread is a daemon and will terminate with the app.")
        # Note: A truly clean shutdown of the Flask dev server from another thread is tricky.
        # For production, use a proper WSGI server like waitress or gunicorn.
        self.server_running = False
        # Update menu item? App is closing anyway.