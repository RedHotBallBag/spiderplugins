# plugins/proxy_rotator_plugin.py
import logging
import random
import json
import time
import threading
from pathlib import Path
from collections import deque
from urllib.parse import urlparse

# Conditional import for requests
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None # Set to None if not available
    REQUESTS_AVAILABLE = False
    logging.warning("Proxy Rotator Plugin: 'requests' library not found. URL source will be disabled.")


from PySide6 import QtWidgets, QtCore, QtGui # Import QtGui
from PySide6.QtCore import QObject, Qt, Slot, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLineEdit,
                               QPlainTextEdit, QSpinBox, QCheckBox, QComboBox,
                               QPushButton, QMessageBox, QGroupBox, QLabel, QHBoxLayout,
                               QProgressDialog, QFileDialog, QApplication) # Added QApplication
from PySide6.QtGui import QIcon # Import QIcon

from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- DEFAULT_CONFIG, CONFIG_PATH remain the same ---
DEFAULT_CONFIG = {
    "enabled_globally": False,
    "proxy_source_type": "list",
    "proxy_list": [],
    "proxy_file": "config/proxies.txt",
    "proxy_url": "",
    "proxy_url_refresh_interval_minutes": 60,
    "rotation_mode": "random",
    "failure_codes": [403, 407, 429, 500, 502, 503, 504],
    "failure_timeout_seconds": 300,
    "max_failed_proxies": 100
}
CONFIG_PATH = Path("config/proxy_rotator_plugin.json")

# --- ProxyRotatorMiddleware remains the same ---
class ProxyRotatorMiddleware(object):
    # ... (Keep the existing middleware code from the previous correct version) ...
    # (Includes __init__, from_crawler, _load_proxies, _refresh_proxies_if_needed,
    #  _get_proxy, _mark_failed, _clear_expired_failures, process_request,
    #  process_response, process_exception)
    def __init__(self, settings):
        self.settings = settings
        self.proxies = []
        self.failed_proxies = {} # {proxy_url: failure_timestamp}
        self.proxy_index = 0 # For sequential mode
        self.last_refresh_time = 0
        self.refresh_lock = threading.Lock() # Prevent concurrent refreshes

        self.enabled = settings.getbool('PROXY_ROTATOR_ENABLED', False)
        self.mode = settings.get('PROXY_ROTATOR_MODE', 'random').lower()
        self.fail_codes = set(settings.getlist('PROXY_ROTATOR_FAIL_CODES', [403, 407, 429, 500, 502, 503, 504]))
        self.fail_timeout = settings.getint('PROXY_ROTATOR_FAIL_TIMEOUT', 300)
        self.proxy_source_type = settings.get('PROXY_ROTATOR_SOURCE_TYPE', 'list')
        self.proxy_list_setting = settings.getlist('PROXY_ROTATOR_PROXY_LIST', [])
        self.proxy_file_setting = settings.get('PROXY_ROTATOR_PROXY_FILE')
        self.proxy_url_setting = settings.get('PROXY_ROTATOR_PROXY_URL')
        self.url_refresh_interval = settings.getint('PROXY_ROTATOR_URL_REFRESH_MINUTES', 60) * 60 # In seconds

        if not self.enabled:
            logger.info("ProxyRotatorMiddleware is disabled by settings.")
            return

        # Check dependency for URL source
        if self.proxy_source_type == 'url' and not REQUESTS_AVAILABLE:
             logger.error("ProxyRotatorMiddleware: 'requests' library is required for URL proxy source but not installed. Disabling middleware.")
             self.enabled = False # Disable if dependency missing for configured source
             return

        self._load_proxies() # Initial load

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def _load_proxies(self):
        new_proxies = []
        source_desc = ""
        try:
            if self.proxy_source_type == 'list':
                source_desc = "settings list"
                new_proxies = [p for p in self.proxy_list_setting if p.strip()]
            elif self.proxy_source_type == 'file':
                source_desc = f"file ({self.proxy_file_setting})"
                if self.proxy_file_setting:
                    path = Path(self.proxy_file_setting)
                    if path.is_file():
                        with open(path, 'r', encoding='utf-8') as f:
                            new_proxies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                    else:
                        logger.error(f"Proxy file not found: {path}")
            elif self.proxy_source_type == 'url':
                source_desc = f"URL ({self.proxy_url_setting})"
                if self.proxy_url_setting and REQUESTS_AVAILABLE: # Check dependency again
                    logger.info(f"Fetching proxies from URL: {self.proxy_url_setting}")
                    response = requests.get(self.proxy_url_setting, timeout=15)
                    response.raise_for_status()
                    new_proxies = [line.strip() for line in response.text.splitlines() if line.strip() and not line.startswith('#')]
                elif not REQUESTS_AVAILABLE:
                     logger.error("Cannot fetch proxies from URL: 'requests' library not installed.")
                self.last_refresh_time = time.time()

            validated_proxies = []
            for p in new_proxies:
                 try:
                      parsed = urlparse(p)
                      if parsed.scheme in ('http', 'https') and parsed.netloc:
                           validated_proxies.append(p)
                      else: logger.warning(f"Ignoring invalid proxy format: {p}")
                 except Exception: logger.warning(f"Ignoring invalid proxy format: {p}")

            if validated_proxies:
                self.proxies = validated_proxies
                self.proxy_index = 0
                logger.info(f"Loaded {len(self.proxies)} proxies from {source_desc}.")
            else:
                 logger.warning(f"No valid proxies loaded from {source_desc}. Rotation inactive.")
                 self.proxies = []

        except requests.RequestException as e: logger.error(f"Failed to fetch proxies from URL {self.proxy_url_setting}: {e}")
        except FileNotFoundError as e: logger.error(f"Proxy file error: {e}"); self.proxies = []
        except Exception as e: logger.exception(f"Error loading proxies from {source_desc}:"); self.proxies = []

    def _refresh_proxies_if_needed(self):
        if self.proxy_source_type != 'url' or not self.url_refresh_interval or not REQUESTS_AVAILABLE:
            return
        now = time.time()
        if now - self.last_refresh_time > self.url_refresh_interval:
            if self.refresh_lock.acquire(blocking=False):
                try:
                    if now - self.last_refresh_time > self.url_refresh_interval:
                        logger.info("Proxy URL refresh interval elapsed, reloading proxies...")
                        self._load_proxies()
                    else: logger.debug("Proxy refresh already done by another process/thread.")
                finally: self.refresh_lock.release()
            else: logger.debug("Proxy refresh is locked, likely being done by another process/thread.")

    def _get_proxy(self):
        if not self.proxies: return None
        self._refresh_proxies_if_needed()
        self._clear_expired_failures()
        available_proxies = [p for p in self.proxies if p not in self.failed_proxies]
        if not available_proxies:
            logger.warning("All configured proxies have recently failed. Clearing failures and retrying.")
            self.failed_proxies.clear()
            available_proxies = self.proxies
            if not available_proxies: logger.error("No proxies available after clearing failures."); return None
        selected_proxy = None
        if self.mode == 'sequential':
            start_index = self.proxy_index % len(self.proxies) # Use full list length for index stability
            for i in range(len(self.proxies)): # Iterate through original list
                 candidate_proxy = self.proxies[(start_index + i) % len(self.proxies)]
                 if candidate_proxy not in self.failed_proxies: # Check if available
                      selected_proxy = candidate_proxy
                      self.proxy_index = (self.proxies.index(selected_proxy) + 1) % len(self.proxies)
                      break
            if not selected_proxy and available_proxies: # Fallback if sequence wrapped without finding available
                 selected_proxy = random.choice(available_proxies) # Pick a random available one
                 if selected_proxy: # Check if fallback found one
                     self.proxy_index = (self.proxies.index(selected_proxy) + 1) % len(self.proxies)

        else: # Random mode
             if available_proxies: # Check if any are actually available
                 selected_proxy = random.choice(available_proxies)
        return selected_proxy

    def _mark_failed(self, proxy):
        if proxy:
            logger.warning(f"Marking proxy as failed: {proxy}")
            self.failed_proxies[proxy] = time.time()

    def _clear_expired_failures(self):
        if not self.fail_timeout: return
        now = time.time()
        expired = [p for p, t in self.failed_proxies.items() if now - t > self.fail_timeout]
        if expired:
            logger.info(f"Re-enabling {len(expired)} proxies after timeout: {', '.join(expired)}")
            for p in expired:
                if p in self.failed_proxies: del self.failed_proxies[p] # Check existence before deleting

    def process_request(self, request, spider):
        if not self.enabled or not self.proxies or 'proxy' in request.meta: return None
        proxy = self._get_proxy()
        if proxy:
            logger.debug(f"Assigning proxy {proxy} to request {request.url}")
            request.meta['proxy'] = proxy
            request.meta['_proxy_rotator_current'] = proxy
        else: logger.error("No available proxies to assign.")

    def process_response(self, request, response, spider):
        if not self.enabled: return response
        proxy = request.meta.get('_proxy_rotator_current')
        if response.status in self.fail_codes:
            logger.warning(f"Proxy {proxy} failed for {response.url} with status {response.status}")
            self._mark_failed(proxy)
        # No explicit action needed on success for now (clearing failures is time-based)
        return response

    # --- Inside ProxyRotatorMiddleware class ---

    def process_exception(self, request, exception, spider):
        if not self.enabled:
            return None # Let other middlewares handle it

        proxy = request.meta.get('_proxy_rotator_current')
        is_proxy_error = False

        # 1. Check for requests.exceptions.ProxyError (if requests is available)
        if requests and isinstance(exception, requests.exceptions.ProxyError):
             is_proxy_error = True

        # 2. Check for specific Twisted errors (if Twisted is available)
        if not is_proxy_error: # Only check if not already identified as proxy error
            try:
                from twisted.internet import error as internet_error
                if isinstance(exception, (internet_error.ConnectionRefusedError,
                                          internet_error.TCPTimedOutError,
                                          internet_error.ConnectionLost,
                                          internet_error.ConnectionDone,
                                          internet_error.TimeoutError)):
                    is_proxy_error = True
            except ImportError:
                pass # Twisted not available, skip these specific checks

        # *** FIX: Unindent the elif to check generic errors AFTER the try/except ***
        # 3. Fallback check for generic exceptions containing keywords
        if not is_proxy_error and isinstance(exception, Exception) and \
           any(err_str in str(exception).lower() for err_str in ["proxy", "timeout", "connection refused"]):
            # Check if it's a generic Exception AND contains keywords AND not already flagged
            is_proxy_error = True

        # 4. Log and mark failed if identified as a proxy-related error
        if is_proxy_error:
            # Use type(exception).__name__ to get the specific error type for logging
            logger.error(f"Proxy {proxy} failed for {request.url} with exception: {type(exception).__name__}")
            self._mark_failed(proxy)

        # Always return None to let Scrapy handle the exception (e.g., retry middleware)
        return None

# --- Spider Manager Plugin (GUI Integration) ---
class Plugin(PluginBase):
    """
    GUI Plugin to configure Proxy Rotation settings.
    """
    def __init__(self):
        super().__init__()
        self.name = "Proxy Rotator"
        self.description = "Configures automatic proxy rotation for Scrapy spiders."
        self.version = "1.0.2" # Version bump
        self.main_window = None
        self.config = DEFAULT_CONFIG.copy()
        self._settings_widget_instance = None # Initialize instance variable
        self._load_config() # Load config on init

    def _load_config(self):
        # (Identical to previous version)
        try:
            if CONFIG_PATH.exists():
                logger.info(f"Loading Proxy Rotator config from {CONFIG_PATH}")
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, default_value in DEFAULT_CONFIG.items():
                         self.config[key] = data.get(key, default_value)
            else:
                 logger.info(f"Proxy Rotator config file not found. Using defaults and saving.")
                 self._save_config() # Save defaults if file missing
        except Exception as e:
            logger.error(f"Failed to load Proxy Rotator plugin config: {e}")
            self.config = DEFAULT_CONFIG.copy()

    def _save_config(self):
        # (Identical to previous version)
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Saved Proxy Rotator config to {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Failed to save Proxy Rotator plugin config: {e}")

    def initialize_ui(self, main_window):
        # (Identical to previous version)
        self.main_window = main_window
        if not REQUESTS_AVAILABLE:
             logger.warning(f"Proxy Rotator Plugin: 'requests' library is missing. URL proxy source will not work.")
        logger.info(f"{self.name} plugin initialized.")

    # *** THIS IS THE FULLY RESTORED METHOD ***
    def _create_settings_widget(self):
        """Return a QWidget for the Preferences dialog."""
        self._settings_widget_instance = QWidget()
        widget = self._settings_widget_instance

        layout = QVBoxLayout(widget)

        # --- Enable ---
        widget.enable_cb = QCheckBox("Enable Proxy Rotation Middleware Globally")
        widget.enable_cb.setChecked(self.config.get("enabled_globally", False))
        widget.enable_cb.setToolTip("If checked, the middleware (if added to settings.py) will be active.")
        layout.addWidget(widget.enable_cb)

        # --- Source ---
        source_group = QGroupBox("Proxy Source")
        source_layout = QFormLayout(source_group)
        widget.source_combo = QComboBox()
        widget.source_combo.addItems(["List in Config", "Local File", "Remote URL"])
        current_source_type = self.config.get("proxy_source_type", "list")
        if current_source_type == "list": widget.source_combo.setCurrentIndex(0)
        elif current_source_type == "file": widget.source_combo.setCurrentIndex(1)
        elif current_source_type == "url": widget.source_combo.setCurrentIndex(2)
        source_layout.addRow("Source Type:", widget.source_combo)

        widget.list_edit = QPlainTextEdit()
        widget.list_edit.setPlaceholderText("http://user:pass@host:port\nhttp://host2:port2")
        widget.list_edit.setPlainText("\n".join(self.config.get("proxy_list", [])))
        widget.list_edit.setVisible(current_source_type == "list")
        source_layout.addRow("Proxy List:", widget.list_edit)

        file_layout = QHBoxLayout()
        widget.file_edit = QLineEdit(self.config.get("proxy_file", DEFAULT_CONFIG["proxy_file"]))
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_proxy_file)
        file_layout.addWidget(widget.file_edit)
        file_layout.addWidget(browse_button)
        widget.file_row_widget = QWidget()
        widget.file_row_widget.setLayout(file_layout)
        widget.file_row_widget.setVisible(current_source_type == "file")
        source_layout.addRow("Proxy File:", widget.file_row_widget)

        widget.url_edit = QLineEdit(self.config.get("proxy_url", ""))
        widget.url_edit.setPlaceholderText("https://your-proxy-provider.com/list.txt")
        widget.url_edit.setVisible(current_source_type == "url")
        source_layout.addRow("Proxy URL:", widget.url_edit)

        widget.url_refresh_spin = QSpinBox()
        widget.url_refresh_spin.setRange(1, 1440)
        widget.url_refresh_spin.setValue(self.config.get("proxy_url_refresh_interval_minutes", 60))
        widget.url_refresh_spin.setSuffix(" minutes")
        widget.url_refresh_spin.setVisible(current_source_type == "url")
        source_layout.addRow("URL Refresh Interval:", widget.url_refresh_spin)

        layout.addWidget(source_group)

        # --- Behavior --- THIS SECTION WAS MISSING ---
        behavior_group = QGroupBox("Rotation Behavior")
        behavior_layout = QFormLayout(behavior_group)

        widget.mode_combo = QComboBox()
        widget.mode_combo.addItems(["random", "sequential"])
        widget.mode_combo.setCurrentText(self.config.get("rotation_mode", "random"))
        behavior_layout.addRow("Rotation Mode:", widget.mode_combo)

        widget.fail_codes_edit = QLineEdit(", ".join(map(str, self.config.get("failure_codes", DEFAULT_CONFIG["failure_codes"]))))
        widget.fail_codes_edit.setPlaceholderText("e.g., 403, 429, 503")
        behavior_layout.addRow("Retry HTTP Codes:", widget.fail_codes_edit)

        widget.fail_timeout_spin = QSpinBox()
        widget.fail_timeout_spin.setRange(0, 3600 * 24)
        widget.fail_timeout_spin.setValue(self.config.get("failure_timeout_seconds", 300))
        widget.fail_timeout_spin.setSuffix(" seconds (0=disable)")
        behavior_layout.addRow("Failed Proxy Cooldown:", widget.fail_timeout_spin)

        layout.addWidget(behavior_group)
        # --- END MISSING SECTION ---

        # --- Instructions --- THIS SECTION WAS MISSING ---
        instr_group = QGroupBox("How to Use")
        instr_layout = QVBoxLayout(instr_group)

        self.middleware_config_text = ( # Store text for copy button
            "DOWNLOADER_MIDDLEWARES = {\n"
            "    # ... other middlewares ...\n"
            "    'plugins.proxy_rotator_plugin.ProxyRotatorMiddleware': 610,\n"
            "    # ... other middlewares ...\n"
            "}"
        )

        pre_style = "background-color:#404040; color:#e0e0e0; padding:8px; border-radius:4px; border: 1px solid #555;"
        instr_html = (
            "<b>1. Configure:</b> Set your proxy source and rotation settings above.<br>"
            "<b>2. Enable Middleware:</b> Add the following to your project's <b>`settings.py`</b>:<br>"
            f"<pre style='{pre_style}'><code>"
            f"{self.middleware_config_text}"
            "</code></pre><br>"
            "<b>3. Enable Globally:</b> Check the 'Enable...' box at the top OR set `PROXY_ROTATOR_ENABLED = True` in `settings.py`."
            "<br><br><i>Note: Settings in `settings.py` override global plugin config for that project.</i>" # Added note
        )
        instr_label = QLabel(instr_html)
        instr_label.setTextFormat(Qt.TextFormat.RichText)
        instr_label.setWordWrap(True)
        instr_label.setOpenExternalLinks(True)
        instr_layout.addWidget(instr_label)

        copy_button_layout = QHBoxLayout()
        copy_button_layout.addStretch()
        copy_instructions_button = QPushButton(QIcon.fromTheme("edit-copy"), "Copy Middleware Config")
        copy_instructions_button.setToolTip("Copy the DOWNLOADER_MIDDLEWARES example to the clipboard")
        copy_instructions_button.clicked.connect(self._copy_instructions_to_clipboard)
        copy_button_layout.addWidget(copy_instructions_button)
        instr_layout.addLayout(copy_button_layout)

        layout.addWidget(instr_group)
        # --- END MISSING SECTION ---

        layout.addStretch()

        # --- Connections ---
        widget.enable_cb.stateChanged.connect(self._save_settings_from_widget)
        widget.source_combo.currentIndexChanged.connect(self._update_source_visibility)
        widget.source_combo.currentIndexChanged.connect(self._save_settings_from_widget)
        widget.list_edit.textChanged.connect(self._save_settings_from_widget)
        widget.file_edit.editingFinished.connect(self._save_settings_from_widget)
        widget.url_edit.editingFinished.connect(self._save_settings_from_widget)
        widget.url_refresh_spin.valueChanged.connect(self._save_settings_from_widget)
        widget.mode_combo.currentIndexChanged.connect(self._save_settings_from_widget)
        widget.fail_codes_edit.editingFinished.connect(self._save_settings_from_widget)
        widget.fail_timeout_spin.valueChanged.connect(self._save_settings_from_widget)

        self._update_source_visibility() # Call once AFTER everything is created

        return widget # Return the main container widget


    @Slot(int)
    def _update_source_visibility(self):
        # (Identical to previous version - uses self._settings_widget_instance)
        widget = self._settings_widget_instance
        if not widget:
             logger.error("Cannot update source visibility: Settings widget instance not found.")
             return
        selected_type = widget.source_combo.currentText()
        is_list = (selected_type == "List in Config")
        is_file = (selected_type == "Local File")
        is_url = (selected_type == "Remote URL")

        # Check if attributes exist before setting visibility (important!)
        if hasattr(widget, 'list_edit'): widget.list_edit.setVisible(is_list)
        if hasattr(widget, 'file_row_widget'): widget.file_row_widget.setVisible(is_file)
        if hasattr(widget, 'url_edit'): widget.url_edit.setVisible(is_url)
        if hasattr(widget, 'url_refresh_spin'): widget.url_refresh_spin.setVisible(is_url)


    @Slot()
    def _browse_proxy_file(self):
        # (Identical to previous version - uses self._settings_widget_instance)
        widget = self._settings_widget_instance
        if not widget: return
        current_path = widget.file_edit.text()
        start_dir = str(Path(current_path).parent) if current_path and Path(current_path).exists() else "."
        file_path, _ = QFileDialog.getOpenFileName(widget, "Select Proxy List File", start_dir, "Text Files (*.txt);;All Files (*)")
        if file_path:
            widget.file_edit.setText(file_path)
            self._save_settings_from_widget()

    # *** THIS IS THE METHOD THAT HAD THE AttributeError ***
    @Slot()
    def _save_settings_from_widget(self):
        """Saves the current state of the settings widget to self.config."""
        widget = self._settings_widget_instance
        if not widget:
             logger.error("Cannot save settings: Settings widget instance not found.")
             return

        try:
            # Source Type
            source_index = widget.source_combo.currentIndex()
            if source_index == 0: self.config["proxy_source_type"] = "list"
            elif source_index == 1: self.config["proxy_source_type"] = "file"
            elif source_index == 2: self.config["proxy_source_type"] = "url"

            # Values from widget attributes
            # Check existence again for robustness
            if hasattr(widget, 'enable_cb'): self.config["enabled_globally"] = widget.enable_cb.isChecked()
            if hasattr(widget, 'list_edit'): self.config["proxy_list"] = [p.strip() for p in widget.list_edit.toPlainText().splitlines() if p.strip()]
            if hasattr(widget, 'file_edit'): self.config["proxy_file"] = widget.file_edit.text().strip()
            if hasattr(widget, 'url_edit'): self.config["proxy_url"] = widget.url_edit.text().strip()
            if hasattr(widget, 'url_refresh_spin'): self.config["proxy_url_refresh_interval_minutes"] = widget.url_refresh_spin.value()
            if hasattr(widget, 'mode_combo'): self.config["rotation_mode"] = widget.mode_combo.currentText()
            if hasattr(widget, 'fail_timeout_spin'): self.config["failure_timeout_seconds"] = widget.fail_timeout_spin.value()

            # Parse failure codes carefully
            if hasattr(widget, 'fail_codes_edit'):
                codes_str = widget.fail_codes_edit.text().strip()
                valid_codes = []
                if codes_str:
                    try:
                        valid_codes = [int(c.strip()) for c in codes_str.split(',') if c.strip().isdigit()]
                    except ValueError:
                        logger.warning(f"Invalid characters found in failure codes: '{codes_str}'. Using previous value.")
                        valid_codes = self.config.get("failure_codes", []) # Fallback
                self.config["failure_codes"] = valid_codes
            else:
                # If fail_codes_edit doesn't exist, keep the existing config value
                self.config["failure_codes"] = self.config.get("failure_codes", [])


            # *** THIS is where the error occurred. self._save_config IS defined. ***
            # The error was likely caused by the incomplete UI creation before.
            # With the UI fully created, this should now work.
            self._save_config() # Persist changes

        except AttributeError as ae:
             # Log specific attribute error if somehow a widget is missing
             logger.error(f"AttributeError accessing settings widget control during save: {ae}. Instance: {widget}")
        except Exception as e:
            logger.exception("Unexpected error saving proxy rotator settings:")


    @Slot()
    def _copy_instructions_to_clipboard(self):
        # (Identical to previous version - uses self.middleware_config_text)
        if hasattr(self, 'middleware_config_text'):
            try:
                clipboard = QApplication.clipboard()
                if clipboard:
                    clipboard.setText(self.middleware_config_text)
                    logger.info("Copied middleware config instructions to clipboard.")
                    if self.main_window and hasattr(self.main_window, 'statusBar'):
                         self.main_window.statusBar().showMessage("Middleware config copied!", 3000)
                else:
                     logger.error("Could not get clipboard instance.")
                     QMessageBox.warning(self._settings_widget_instance or self.main_window, "Clipboard Error", "Could not access system clipboard.")
            except Exception as e:
                logger.error(f"Failed to copy instructions to clipboard: {e}")
                QMessageBox.warning(self._settings_widget_instance or self.main_window, "Clipboard Error", f"Could not copy instructions:\n{e}")
        else:
             logger.error("middleware_config_text not defined on plugin instance.")


    def on_app_exit(self):
        # (Identical to previous version)
        self._save_config()
        self._settings_widget_instance = None
        logger.info(f"{self.name} plugin exiting.")