import logging
import sys
import json
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QColor, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QTreeWidget, QTreeWidgetItem, QPushButton,
                               QDialogButtonBox, QMessageBox, QFileDialog,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QTabWidget, QWidget, QTextBrowser, QSizePolicy,
                               QApplication)
from PySide6.QtCore import Qt, Slot

# Import Plugin Base
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Regex Patterns for Log Parsing ---
# Adjust these if Scrapy log format changes significantly
REGEX_ERROR = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[\S+\] ERROR: (.*)")
REGEX_WARNING = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[\S+\] WARNING: (.*)")
REGEX_ITEM_SCRAPED = re.compile(r"'item_scraped_count': (\d+)")
REGEX_FINISH_REASON = re.compile(r"'finish_reason': '([^']*)'")
REGEX_ELAPSED_TIME = re.compile(r"'elapsed_time_seconds': (\d+\.?\d*)")
REGEX_REQUEST_COUNT = re.compile(r"'downloader/request_count': (\d+)")
REGEX_REQUEST_BYTES = re.compile(r"'downloader/request_bytes': (\d+)")
REGEX_RESPONSE_COUNT = re.compile(r"'downloader/response_count': (\d+)")
REGEX_RESPONSE_BYTES = re.compile(r"'downloader/response_bytes': (\d+)")
REGEX_RESPONSE_STATUS = re.compile(r"'downloader/response_status_count/(\d+)': (\d+)")


# --- Log Analyzer Dialog ---
class LogAnalyzerDialog(QDialog):
    """Dialog to display structured log analysis results."""
    def __init__(self, log_file_path: Path, analysis_results: dict, parent=None):
        super().__init__(parent)
        self.log_file_path = log_file_path
        self.results = analysis_results
        self.setWindowTitle(f"Log Analysis: {log_file_path.name}")
        self.setMinimumSize(750, 550)
        self._init_ui()
        self.populate_results()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)

        # Title/File Label
        title_label = QLabel(f"<b>Analysis for:</b> {self.log_file_path}")
        title_label.setWordWrap(True)
        main_layout.addWidget(title_label)

        # Tab Widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # -- Summary Tab --
        self.summary_tab = QWidget()
        summary_layout = QVBoxLayout(self.summary_tab)
        self.summary_browser = QTextBrowser() # Use browser for rich text
        self.summary_browser.setOpenExternalLinks(True)
        summary_layout.addWidget(self.summary_browser)
        self.tab_widget.addTab(self.summary_tab, "📊 Summary")

        # -- Errors Tab --
        self.errors_tab = QWidget()
        errors_layout = QVBoxLayout(self.errors_tab)
        self.errors_table = QTableWidget()
        self.errors_table.setColumnCount(2)
        self.errors_table.setHorizontalHeaderLabels(["Count", "Error Message"])
        self.errors_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.errors_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.errors_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.errors_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.errors_table.setAlternatingRowColors(True)
        errors_layout.addWidget(self.errors_table)
        self.tab_widget.addTab(self.errors_tab, "❌ Errors")

        # -- Warnings Tab --
        self.warnings_tab = QWidget()
        warnings_layout = QVBoxLayout(self.warnings_tab)
        self.warnings_table = QTableWidget()
        self.warnings_table.setColumnCount(2)
        self.warnings_table.setHorizontalHeaderLabels(["Count", "Warning Message"])
        self.warnings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.warnings_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.warnings_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.warnings_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.warnings_table.setAlternatingRowColors(True)
        warnings_layout.addWidget(self.warnings_table)
        self.tab_widget.addTab(self.warnings_tab, "⚠️ Warnings")

        # -- Raw Stats Tab --
        self.stats_tab = QWidget()
        stats_layout = QVBoxLayout(self.stats_tab)
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Stat Key", "Value"])
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.stats_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stats_table.setAlternatingRowColors(True)
        stats_layout.addWidget(self.stats_table)
        self.tab_widget.addTab(self.stats_tab, "Raw Stats")

        # --- Close Button ---
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def populate_results(self):
        """Fill the tabs with the analyzed data."""
        stats = self.results.get('stats', {})
        errors = self.results.get('errors', {})
        warnings = self.results.get('warnings', {})
        summary_info = self.results.get('summary', {})

        # --- Populate Summary Tab ---
        summary_html = "<h2>Run Summary</h2><table border='0' cellspacing='5'>"
        summary_map = {
            "finish_reason": "Finish Reason",
            "item_scraped_count": "Items Scraped",
            "elapsed_seconds": "Elapsed Time (s)",
            "total_requests": "Total Requests",
            "total_responses": "Total Responses",
            "error_count": "Total Errors",
            "warning_count": "Total Warnings",
            "avg_req_per_sec": "Avg. Requests/sec",
            "avg_item_per_sec": "Avg. Items/sec",
            "http_success_rate": "HTTP Success Rate (%)"
        }
        for key, label in summary_map.items():
            value = summary_info.get(key, "N/A")
            # Format floats nicely
            if isinstance(value, float):
                value = f"{value:.2f}"
            summary_html += f"<tr><td><b>{label}:</b></td><td>{value}</td></tr>"

        # Status code summary
        status_codes = stats.get('status_codes', {})
        if status_codes:
             summary_html += "<tr><td colspan='2'><br><b>HTTP Status Codes:</b></td></tr>"
             for code, count in sorted(status_codes.items()):
                 color = "green" if code.startswith('2') else ("orange" if code.startswith('3') else "red")
                 summary_html += f"<tr><td style='padding-left: 15px; color:{color};'>{code}:</td><td>{count}</td></tr>"

        summary_html += "</table>"
        self.summary_browser.setHtml(summary_html)

        # --- Populate Errors Tab ---
        self.errors_table.setRowCount(len(errors))
        for i, (msg, count) in enumerate(errors.items()):
             count_item = QTableWidgetItem(str(count))
             count_item.setTextAlignment(Qt.AlignCenter)
             self.errors_table.setItem(i, 0, count_item)
             self.errors_table.setItem(i, 1, QTableWidgetItem(msg))
        self.errors_table.resizeRowsToContents()
        self.tab_widget.setTabText(1, f"❌ Errors ({len(errors)})") # Update tab title with count

        # --- Populate Warnings Tab ---
        self.warnings_table.setRowCount(len(warnings))
        for i, (msg, count) in enumerate(warnings.items()):
             count_item = QTableWidgetItem(str(count))
             count_item.setTextAlignment(Qt.AlignCenter)
             self.warnings_table.setItem(i, 0, count_item)
             self.warnings_table.setItem(i, 1, QTableWidgetItem(msg))
        self.warnings_table.resizeRowsToContents()
        self.tab_widget.setTabText(2, f"⚠️ Warnings ({len(warnings)})") # Update tab title

        # --- Populate Raw Stats Tab ---
        raw_stats = stats.get('raw_stats', {})
        self.stats_table.setRowCount(len(raw_stats))
        for i, (key, value) in enumerate(sorted(raw_stats.items())):
             self.stats_table.setItem(i, 0, QTableWidgetItem(key))
             self.stats_table.setItem(i, 1, QTableWidgetItem(str(value)))
        self.stats_table.resizeRowsToContents()
        self.stats_table.resizeColumnToContents(0)


# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Scrapy Log Analyzer Plugin.
    """
    def __init__(self):
        super().__init__()
        self.name = "Log Analyzer"
        self.description = "Analyzes Scrapy log files for stats, errors, and warnings."
        self.version = "1.0.0"
        self.main_window = None
        self.logs_dir = None # Will be set in initialize

    def initialize_ui(self, main_window):
        """Add menu item to trigger the log analyzer dialog."""
        self.main_window = main_window

        # Determine logs directory
        self.logs_dir = self.main_window.logs_dir if hasattr(self.main_window, 'logs_dir') else Path("data/logs")
        if not self.logs_dir.is_dir():
            logger.warning(f"{self.name}: Logs directory '{self.logs_dir}' not found. File dialog might not start there.")

        if not hasattr(main_window, 'menuBar'):
            logger.error(f"{self.name}: MainWindow is missing 'menuBar'. Skipping menu item add.")
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

        analyze_action = QAction(QIcon.fromTheme("document-preview", QIcon.fromTheme("analyze")), # Try preview or analyze icon
                                "Analyze Scrapy Log...", main_window)
        analyze_action.setToolTip("Select a Scrapy log file to analyze its content.")
        analyze_action.triggered.connect(self._show_analyzer_dialog)
        tools_menu.addAction(analyze_action)

        logger.info(f"{self.name} plugin initialized UI.")


    @Slot()
    def _show_analyzer_dialog(self):
        """Opens a file dialog and then the analyzer dialog."""
        start_dir = str(self.logs_dir) if self.logs_dir and self.logs_dir.exists() else ""
        log_file_path_str, _ = QFileDialog.getOpenFileName(
            self.main_window,
            "Select Scrapy Log File",
            start_dir,
            "Log Files (*.log);;All Files (*)"
        )

        if not log_file_path_str:
            return # User cancelled

        log_file_path = Path(log_file_path_str)

        # Run analysis (usually fast enough for dialog, consider threading for huge logs)
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor) # Indicate processing
            results = self._analyze_log_file(log_file_path)
        except Exception as e:
             QApplication.restoreOverrideCursor()
             logger.exception(f"Error analyzing log file {log_file_path}:")
             QMessageBox.critical(self.main_window, "Analysis Failed", f"Could not analyze log file:\n{e}")
             return
        finally:
             QApplication.restoreOverrideCursor()


        # Show dialog
        dialog = LogAnalyzerDialog(log_file_path, results, self.main_window)
        dialog.exec()


    def _analyze_log_file(self, log_file_path: Path):
        """Reads and analyzes the content of a Scrapy log file."""
        logger.info(f"Analyzing log file: {log_file_path}")
        results = {
            'errors': defaultdict(int),
            'warnings': defaultdict(int),
            'stats': {
                'raw_stats': {},
                'status_codes': defaultdict(int)
            },
            'summary': {}
        }
        line_count = 0
        in_stats_dump = False

        try:
            with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line_count += 1
                    line = line.strip()
                    if not line: continue

                    # Check for Errors
                    error_match = REGEX_ERROR.match(line)
                    if error_match:
                        msg = error_match.group(1).strip()
                        # Basic grouping for common tracebacks
                        if 'Traceback (most recent call last)' in msg:
                             msg = "Traceback occurred (see log for details)"
                        results['errors'][msg] += 1
                        continue # Processed as error

                    # Check for Warnings
                    warning_match = REGEX_WARNING.match(line)
                    if warning_match:
                        msg = warning_match.group(1).strip()
                        results['warnings'][msg] += 1
                        continue # Processed as warning

                    # Detect start/end of final stats dump
                    if line == '}': in_stats_dump = False # End of stats
                    if in_stats_dump:
                        parts = line.split(': ')
                        if len(parts) == 2:
                             key = parts[0].strip().strip("'")
                             value_str = parts[1].strip().strip(',')
                             try:
                                 # Try converting to number if possible
                                 value = json.loads(value_str)
                             except json.JSONDecodeError:
                                 value = value_str.strip("'") # Keep as string if not JSON parsable

                             results['stats']['raw_stats'][key] = value

                             # Extract specific status codes
                             status_match = REGEX_RESPONSE_STATUS.match(key)
                             if status_match:
                                  results['stats']['status_codes'][status_match.group(1)] += int(value)

                    if "'downloader/response_count':" in line: # Start of stats dump
                        in_stats_dump = True
                        # Also process the first line of stats
                        parts = line.split(': ')
                        if len(parts) == 2:
                             key = parts[0].strip().strip("'")
                             value_str = parts[1].strip().strip(',')
                             try: value = json.loads(value_str)
                             except: value = value_str.strip("'")
                             results['stats']['raw_stats'][key] = value

            # --- Post-Processing / Summary Calculation ---
            raw_stats = results['stats']['raw_stats']
            summary = results['summary']
            summary['error_count'] = sum(results['errors'].values())
            summary['warning_count'] = sum(results['warnings'].values())
            summary['item_scraped_count'] = raw_stats.get('item_scraped_count', 0)
            summary['finish_reason'] = raw_stats.get('finish_reason', 'N/A')
            summary['elapsed_seconds'] = raw_stats.get('elapsed_time_seconds', 0.0)
            summary['total_requests'] = raw_stats.get('downloader/request_count', 0)
            summary['total_responses'] = raw_stats.get('downloader/response_count', 0)

            if summary['elapsed_seconds'] > 0:
                 summary['avg_req_per_sec'] = summary['total_requests'] / summary['elapsed_seconds']
                 summary['avg_item_per_sec'] = summary['item_scraped_count'] / summary['elapsed_seconds']
            else:
                 summary['avg_req_per_sec'] = 0.0
                 summary['avg_item_per_sec'] = 0.0

            # Calculate HTTP Success Rate (2xx codes / total responses)
            success_codes = sum(count for code, count in results['stats']['status_codes'].items() if code.startswith('2'))
            if summary['total_responses'] > 0:
                 summary['http_success_rate'] = (success_codes / summary['total_responses']) * 100.0
            else:
                 summary['http_success_rate'] = 0.0


            logger.info(f"Log analysis complete. Lines processed: {line_count}")

        except FileNotFoundError:
            raise Exception(f"Log file not found: {log_file_path}")
        except Exception as e:
            raise Exception(f"Failed to read or parse log file: {e}")

        return results


    def on_app_exit(self):
        """Placeholder for cleanup if needed."""
        logger.info(f"{self.name} plugin exiting.")