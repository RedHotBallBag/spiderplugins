# plugins/console_plugin.py
import logging
import sys
import queue
from datetime import datetime
from pathlib import Path

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Qt, Slot, Signal, QTimer
from PySide6.QtGui import QColor, QTextCursor, QFont, QAction, QIcon

from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

class QueueHandler(logging.Handler):
    """
    A logging handler that puts the logs into a queue for later processing
    by the GUI.
    """
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        self.log_queue.put(record)

class ConsoleWidget(QtWidgets.QWidget):
    """
    The main console widget that shows the log messages.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        
        # Set the level you want to capture
        self.queue_handler.setLevel(logging.DEBUG)
        
        # Add the handler to the root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self.queue_handler)
        
        self._init_ui()
        
        # Start timer to check for new logs
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_logs)
        self.timer.start(100)  # Check every 100ms
        
        # Store the log levels we want to display
        self.visible_levels = {
            logging.DEBUG: True,
            logging.INFO: True,
            logging.WARNING: True,
            logging.ERROR: True,
            logging.CRITICAL: True
        }
        
        # Create file to store logs
        self.log_file = Path("data/console_logs.txt")
        self.log_file.parent.mkdir(exist_ok=True)
        
    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Create toolbar
        toolbar = QtWidgets.QHBoxLayout()
        
        # Add filter by level buttons
        self.level_buttons = {}
        for level, label, color in [
            (logging.DEBUG, "DEBUG", "#AAAAAA"),
            (logging.INFO, "INFO", "#FFFFFF"),
            (logging.WARNING, "WARN", "#FFD700"),
            (logging.ERROR, "ERROR", "#FF6347"),
            (logging.CRITICAL, "CRIT", "#FF0000")
        ]:
            btn = QtWidgets.QCheckBox(label)
            btn.setChecked(True)
            btn.setStyleSheet(f"color: {color};")
            btn.stateChanged.connect(lambda state, lvl=level: self._toggle_level(lvl, state))
            toolbar.addWidget(btn)
            self.level_buttons[level] = btn
        
        # Add clear button
        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_console)
        toolbar.addWidget(clear_btn)
        
        # Add save button
        save_btn = QtWidgets.QPushButton("Save Logs")
        save_btn.clicked.connect(self._save_logs)
        toolbar.addWidget(save_btn)
        
        # Add search field
        toolbar.addStretch()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search logs...")
        self.search_input.textChanged.connect(self._filter_logs)
        toolbar.addWidget(self.search_input)
        
        layout.addLayout(toolbar)
        
        # Create console output view
        self.console = QtWidgets.QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #000000; color: #FFFFFF;")
        font = QFont("Consolas", 10)
        font.setFixedPitch(True)
        self.console.setFont(font)
        layout.addWidget(self.console)
        
        # Store original logs
        self.log_records = []
        
    def process_logs(self):
        """Process any new log messages in the queue."""
        try:
            while True:  # Process all queued messages
                record = self.log_queue.get_nowait()
                self._process_log_record(record)
                self.log_queue.task_done()
        except queue.Empty:
            pass  # No more items in the queue
            
    def _process_log_record(self, record):
        """Process a single log record."""
        # Store the record
        self.log_records.append(record)
        
        # Only display if this level is visible
        if not self.visible_levels.get(record.levelno, True):
            return
            
        # Skip if there's a search filter and this doesn't match
        search_text = self.search_input.text().lower()
        if search_text and search_text not in record.getMessage().lower():
            return
        
        # Format the message
        formatter = self.queue_handler.formatter
        msg = formatter.format(record)
        
        # Set color based on level
        color = self._get_level_color(record.levelno)
        
        # Add to console
        self.console.moveCursor(QTextCursor.End)
        self.console.setTextColor(color)
        self.console.insertPlainText(msg + "\n")
        self.console.moveCursor(QTextCursor.End)  # Auto-scroll to end
        
        # Also save to log file
        try:
            with open(self.log_file, "a") as f:
                f.write(msg + "\n")
        except Exception as e:
            # Don't log this error as it would cause recursion
            print(f"Error writing to console log file: {e}")
        
    def _get_level_color(self, level):
        """Get the color for a log level."""
        if level == logging.DEBUG:
            return QColor("#AAAAAA")  # Gray
        elif level == logging.INFO:
            return QColor("#FFFFFF")  # White
        elif level == logging.WARNING:
            return QColor("#FFD700")  # Gold
        elif level == logging.ERROR:
            return QColor("#FF6347")  # Tomato
        elif level == logging.CRITICAL:
            return QColor("#FF0000")  # Red
        return QColor("#FFFFFF")  # Default white
    
    def _toggle_level(self, level, state):
        """Toggle visibility of a log level."""
        self.visible_levels[level] = bool(state)
        self._rerender_logs()
        
    def _filter_logs(self):
        """Filter logs based on search text."""
        self._rerender_logs()
        
    def _rerender_logs(self):
        """Rerender all logs with current filters."""
        # Save the current position
        vscroll = self.console.verticalScrollBar().value()
        
        # Clear the console
        self.console.clear()
        
        # Re-add all matching records
        search_text = self.search_input.text().lower()
        for record in self.log_records:
            # Skip if level is hidden
            if not self.visible_levels.get(record.levelno, True):
                continue
                
            # Skip if doesn't match search
            if search_text and search_text not in record.getMessage().lower():
                continue
            
            # Format and add the record
            formatter = self.queue_handler.formatter
            msg = formatter.format(record)
            color = self._get_level_color(record.levelno)
            
            self.console.moveCursor(QTextCursor.End)
            self.console.setTextColor(color)
            self.console.insertPlainText(msg + "\n")
        
        # Restore position if needed, or scroll to end
        if search_text:
            # If searching, set cursor at the beginning to see first result
            self.console.moveCursor(QTextCursor.Start)
        else:
            # Try to restore the previous position
            self.console.verticalScrollBar().setValue(vscroll)
    
    def _clear_console(self):
        """Clear the console display but keep the logs in memory."""
        self.console.clear()
    
    def _save_logs(self):
        """Save logs to a file."""
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Logs", "", "Log Files (*.log);;Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return
            
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                for record in self.log_records:
                    formatter = self.queue_handler.formatter
                    msg = formatter.format(record)
                    f.write(msg + "\n")
            
            # Show success message
            QtWidgets.QMessageBox.information(
                self, "Logs Saved", f"Logs successfully saved to:\n{file_path}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Failed to save logs: {e}"
            )

class Plugin(PluginBase):
    """
    Console Plugin for Scrapy Spider Manager.
    Shows application logs in a console panel with highlighting.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Console"
        self.description = "Displays application logs in a console panel"
        self.version = "1.0.0"
        self.main_window = None
        self.console_tab = None
        
    def initialize_ui(self, main_window):
        """Create and add the console tab."""
        self.main_window = main_window
        
        # Create console widget
        self.console_tab = ConsoleWidget()
        
        # Add to tab widget if available
        if hasattr(main_window, 'tab_widget'):
            icon = QIcon.fromTheme("utilities-terminal", QIcon())  # Use terminal icon
            main_window.tab_widget.addTab(self.console_tab, icon, "Console")
            logger.info("Console plugin initialized UI")
        else:
            logger.error("Could not find main window's tab_widget")
            
    def on_spider_started(self, spider_info):
        """Add extra logging for spider start events."""
        spider_name = spider_info.get('spider_name', 'unknown')
        project_name = spider_info.get('project_name', 'unknown')
        logger.info(f"CONSOLE PLUGIN: Spider started: {project_name}/{spider_name}")
        
    def on_spider_finished(self, spider_info, status, item_count):
        """Add extra logging for spider finish events."""
        spider_name = spider_info.get('spider_name', 'unknown')
        project_name = spider_info.get('project_name', 'unknown')
        logger.info(f"CONSOLE PLUGIN: Spider finished: {project_name}/{spider_name} - Status: {status} - Items: {item_count}")
        
    def on_app_exit(self):
        """Perform clean up if needed."""
        logger.info("Console plugin exiting")