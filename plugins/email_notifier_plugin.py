# plugins/email_notifier_plugin.py
import logging
import sys
import json
import os
import re
import csv
import time
import uuid
import smtplib
import functools
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QIcon, QFont, QColor, QAction
from PySide6.QtCore import Qt, Slot, QSize, QTimer, QThread, Signal, QObject, QPoint
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                            QLabel, QLineEdit, QTextEdit, QPushButton, QGroupBox,
                            QGridLayout, QFormLayout, QMessageBox, QDialog,
                            QDialogButtonBox, QComboBox, QCheckBox, QFileDialog,
                            QTableWidget, QTableWidgetItem, QHeaderView,
                            QProgressBar, QScrollArea, QApplication, QSpinBox)

# Import Plugin Base
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Constants for this plugin ---
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_FILE = BASE_DIR / "config" / "email_notifier_plugin.json" # Specific config file
DEFAULT_CONFIG = {
    "email_connections": {},
    "auto_notification": {
        "enabled": False,
        "spider": "Any Spider",
        "connection": "",
        "recipients": "",
        "template": "Basic Summary",
        "attach_results": False,
        "subject": "[Scrapy] {spider_name} Completed - {item_count} Items",
        "message": "Spider: {spider_name}\nStarted: {start_time}\nFinished: {finish_time}\nDuration: {duration}\nItems Scraped: {item_count}\nErrors: {error_count}"
    }
}

# --- Task Runner (Only needs email task) ---
class EmailTaskThread(QThread):
    """Thread to send email without blocking UI"""
    result_signal = Signal(bool, str, object)  # success, message, result_data
    log_signal = Signal(str, str)  # level, message
    # No progress signal needed for simple email send

    def __init__(self, task_data):
        super().__init__()
        self.task_data = task_data
        self._is_cancelled = False # Although not used in simple send, keep for consistency

    def run(self):
        try:
            self.log_signal.emit("info", "Starting email task...")
            self._run_email_task() # Directly call email task
        except InterruptedError:
            self.log_signal.emit("warning", "Email task cancelled.")
            self.result_signal.emit(False, "Task Cancelled", None)
        except Exception as e:
            logger.error(f"Error in email task run method: {e}", exc_info=True)
            self.log_signal.emit("error", f"Internal Task Error: {str(e)}")
            self.result_signal.emit(False, f"Task failed: {str(e)}", None)

    def cancel(self):
        self.log_signal.emit("info", "Email task cancellation requested.")
        self._is_cancelled = True # Set flag, though not checked in this simple version

    def _run_email_task(self):
        """Sends email based on task_data."""
        # Identical logic to the email task in the previous TaskThread
        email_config = self.task_data.get("email_config", {})
        recipients = self.task_data.get("recipients", [])
        subject = self.task_data.get("subject", "Scrapy Notification")
        message_body = self.task_data.get("message", "")
        attachment_path_str = self.task_data.get("attachment_path")

        debug_config = {k: (v if k != "smtp_password" else "********") for k, v in email_config.items()}
        self.log_signal.emit("info", f"Email Config: {debug_config}")

        if not recipients: self.result_signal.emit(False, "No recipients", None); return
        required = ["smtp_server", "smtp_port", "smtp_username", "smtp_password"]
        missing = [f for f in required if not email_config.get(f)]
        if missing: self.result_signal.emit(False, f"Missing config: {', '.join(missing)}", None); return

        self.log_signal.emit("info", f"Preparing email for: {', '.join(recipients)}")
        server = None
        try:
            smtp_server = email_config["smtp_server"]; smtp_port = int(email_config["smtp_port"])
            smtp_username = email_config["smtp_username"]; smtp_password = email_config["smtp_password"]
            sender = email_config.get("sender") or smtp_username; use_ssl = email_config.get("use_ssl", False)
            use_tls = email_config.get("use_tls", True)

            msg = MIMEMultipart()
            msg['From'] = sender; msg['To'] = ", ".join(recipients); msg['Subject'] = subject
            msg.attach(MIMEText(message_body, 'plain', 'utf-8'))

            if attachment_path_str:
                attachment_path = Path(attachment_path_str)
                if attachment_path.is_file():
                    try:
                        attach_name = attachment_path.name
                        with open(attachment_path, "rb") as attach_file: part = MIMEApplication(attach_file.read(), Name=attach_name)
                        part['Content-Disposition'] = f'attachment; filename="{attach_name}"'; msg.attach(part)
                        self.log_signal.emit("info", f"Attaching file: {attach_name}")
                    except Exception as attach_err: self.log_signal.emit("error", f"Failed to attach {attachment_path}: {attach_err}")
                else: self.log_signal.emit("warning", f"Attachment not found: {attachment_path}")

            self.log_signal.emit("info", f"Connecting {smtp_server}:{smtp_port}");
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) if use_ssl else smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            if use_tls and not use_ssl: self.log_signal.emit("debug","Starting TLS..."); server.starttls()
            self.log_signal.emit("info", f"Logging in as {smtp_username}"); server.login(smtp_username, smtp_password);
            self.log_signal.emit("info","Sending..."); server.sendmail(sender, recipients, msg.as_string()); server.quit(); server=None
            self.log_signal.emit("info","Email sent OK."); self.result_signal.emit(True,"Email sent successfully",{"recipients":recipients})
        except Exception as e: err_msg = f"Send fail: {e}"; self.log_signal.emit("error", err_msg); self.result_signal.emit(False, err_msg, None); logger.error("Email Task Error", exc_info=True)
        finally:
            if server:
                try: 
                    server.quit()
                    self.log_signal.emit("debug","SMTP server quit.")
                except: pass


# --- Task Runner Dialog (Can be reused) ---
class TaskRunnerDialog(QDialog):
     # --- Keep EXACTLY as in the previous fully working version ---
     def __init__(self, task_type, task_title, parent=None): super().__init__(parent); self.task_type=task_type; self.thread=None; self.setWindowTitle(f"Running {task_title}"); self.setMinimumWidth(400); self.setMinimumHeight(250); self._init_ui()
     def _init_ui(self): layout=QVBoxLayout(self); self.status_label=QLabel("Starting task...");self.status_label.setAlignment(Qt.AlignCenter);layout.addWidget(self.status_label); self.progress_bar=QProgressBar(); self.progress_bar.setRange(0,100); self.progress_bar.setValue(0); layout.addWidget(self.progress_bar); log_group=QGroupBox("Task Log"); log_layout=QVBoxLayout(); self.log_display=QTextEdit(); self.log_display.setReadOnly(True); self.log_display.setFont(QFont("Courier",9)); log_layout.addWidget(self.log_display,1); log_group.setLayout(log_layout); layout.addWidget(log_group,1); button_layout=QHBoxLayout(); self.cancel_button=QPushButton("Cancel"); self.cancel_button.clicked.connect(self.reject); button_layout.addWidget(self.cancel_button); self.close_button=QPushButton("Close"); self.close_button.setEnabled(False); self.close_button.clicked.connect(self.accept); button_layout.addWidget(self.close_button); layout.addLayout(button_layout)
     def set_thread(self, thread: EmailTaskThread): self.thread = thread; self.thread.result_signal.connect(self.task_completed); self.thread.log_signal.connect(self.add_log); self.rejected.connect(thread.cancel); # Connect cancel
     # Remove progress signal connection if not used by EmailTaskThread
     # self.thread.progress_signal.connect(self.update_progress)
     @Slot(int, int, str) # Keep slot in case other tasks use it later, but email task doesn't emit progress
     def update_progress(self, current, total, message=None): self.progress_bar.setMaximum(total); self.progress_bar.setValue(current); message and self.status_label.setText(message)
     @Slot(bool, str, object)
     def task_completed(self, success, message, result_data): self.progress_bar.setValue(self.progress_bar.maximum()); self.status_label.setText(message); self.status_label.setStyleSheet(f"color:{'green' if success else 'red'};font-weight:bold;"); self.add_log("info" if success else "error",f"Task finished: {message}"); self.close_button.setEnabled(True); self.cancel_button.setEnabled(False); self.cancel_button.setText("Finished")
     @Slot(str, str)
     def add_log(self, level, message): ts=datetime.now().strftime("%H:%M:%S.%f")[:-3]; colors={"error":"red","warning":"orange","info":"blue","debug":"gray"}; color=colors.get(level.lower(),"black"); entry=f"<span style='color:{color};'>[{ts}] {level.upper()}: {message}</span>"; self.log_display.append(entry); self.log_display.verticalScrollBar().setValue(self.log_display.verticalScrollBar().maximum())
     def reject(self):
         if self.thread and self.thread.isRunning(): self.thread.cancel(); self.status_label.setText("Cancelling..."); self.cancel_button.setEnabled(False);
         else: super().reject()


# --- Email Config Dialog (Keep as previously corrected) ---
class EmailConfigDialog(QDialog): # Removed base class inheritance temporarily
    def __init__(self, connection_id=None, config=None, parent=None):
        super().__init__(parent)
        self.connection_id = connection_id
        self.config = config.copy() if config else {}
        self.setMinimumWidth(500)
        self.setWindowTitle(f"{'Edit' if connection_id else 'Add'} Email Connection")
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self.form_layout = QFormLayout() # Use QFormLayout directly
        layout.addLayout(self.form_layout)

        self.name_input=QLineEdit(self.connection_id or "")
        self.form_layout.addRow("Connection Name*:", self.name_input)
        # Directly call the field init method
        self._init_specific_fields()

        self.test_button = QPushButton("Test Connection")
        self.test_button.clicked.connect(self.test_connection)
        layout.addWidget(self.test_button)
        self.status_label=QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(30)
        layout.addWidget(self.status_label)

        w=QLabel("<b>Gmail Users:</b> Use an App Password. <a href='https://support.google.com/accounts/answer/185833'>More Info</a>")
        w.setOpenExternalLinks(True)
        w.setStyleSheet("background-color:#ffffe0; padding:5px; border:1px solid #ccc; border-radius: 3px;")
        layout.addWidget(w)

        btns=QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _init_specific_fields(self):
        self.smtp_server_input=QLineEdit(self.config.get("smtp_server",""))
        self.form_layout.addRow("SMTP Server*:",self.smtp_server_input)
        self.smtp_port_input=QSpinBox()
        self.smtp_port_input.setRange(1,65535)
        self.smtp_port_input.setValue(int(self.config.get("smtp_port",587)))
        self.form_layout.addRow("SMTP Port*:",self.smtp_port_input)
        self.smtp_username_input=QLineEdit(self.config.get("smtp_username",""))
        self.form_layout.addRow("SMTP Username*:",self.smtp_username_input)
        self.smtp_password_input=QLineEdit(self.config.get("smtp_password",""))
        self.smtp_password_input.setEchoMode(QLineEdit.Password)
        self.form_layout.addRow("SMTP Password*:",self.smtp_password_input)
        self.sender_input=QLineEdit(self.config.get("sender",""))
        self.sender_input.setPlaceholderText("(Optional) Defaults to username")
        self.form_layout.addRow("Sender Email:",self.sender_input)
        self.use_ssl_checkbox=QCheckBox("Use SSL")
        self.use_ssl_checkbox.setChecked(self.config.get("use_ssl",False))
        self.form_layout.addRow("",self.use_ssl_checkbox)
        self.use_tls_checkbox=QCheckBox("Use STARTTLS (Recommended)")
        self.use_tls_checkbox.setChecked(self.config.get("use_tls",True))
        self.form_layout.addRow("",self.use_tls_checkbox)

    def test_connection(self):
        """Test the SMTP connection without causing app crashes"""
        self.status_label.setText("Testing connection...")
        self.status_label.setStyleSheet("color:blue;")
        QApplication.processEvents()
        
        # Get config and validate
        config = self.get_config()
        if not all(config.get(k) for k in ["smtp_server", "smtp_username", "smtp_password"]):
            self._set_test_result(False, "Server, Username, and Password are required")
            return
            
        # Create a local thread that won't be garbage collected
        test_thread = EmailTaskThread({
            "email_config": config,
            "recipients": ["test@example.com"],  # Dummy recipient just for test
            "subject": "Test Connection",
            "message": "SMTP Test"
        })
        
        # Store thread reference in the dialog to prevent premature garbage collection
        self.test_thread = test_thread
        
        # Connect signals for test results
        test_thread.result_signal.connect(self._handle_test_result)
        test_thread.log_signal.connect(lambda level, msg: logger.debug(f"Email Test Log ({level}): {msg}"))
        
        # Start the thread
        test_thread.start()

    def _handle_test_result(self, success, message, data):
        """Handle test connection result (separate from _set_test_result)"""
        self._set_test_result(success, f"Test Result: {message}")
        # Help garbage collection
        if hasattr(self, 'test_thread'):
            self.test_thread = None

    def _set_test_result(self, success, message):
        """Set the test result message"""
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color:{'green' if success else 'red'};")


    def get_config(self):
        return {
            "smtp_server":self.smtp_server_input.text().strip(),
            "smtp_port":self.smtp_port_input.value(),
            "smtp_username":self.smtp_username_input.text().strip(),
            "smtp_password":self.smtp_password_input.text(),
            "sender":self.sender_input.text().strip() or self.smtp_username_input.text().strip(),
            "use_ssl":self.use_ssl_checkbox.isChecked(),
            "use_tls":self.use_tls_checkbox.isChecked()
        }

    def validate(self):
        if not self.smtp_server_input.text().strip(): QMessageBox.warning(self,"Input Error","SMTP Server req."); return False
        if not self.smtp_username_input.text().strip(): QMessageBox.warning(self,"Input Error","SMTP User req."); return False
        if not self.smtp_password_input.text(): QMessageBox.warning(self,"Input Error","SMTP Pass req."); return False
        return True

    def _set_test_result(self, success, message):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color:{'green' if success else 'red'};")

    def accept(self):
        name = self.name_input.text().strip()
        if not name: QMessageBox.warning(self,"Input Error","Name required."); return
        if not self.validate(): return
        self.connection_id = name
        super().accept()


# --- Main Email Notifier Widget ---
class EmailNotifierWidget(QWidget):
    """The main widget for the Email Notifier tab."""
    def __init__(self, plugin_instance, parent=None):
        super().__init__(parent)
        self.plugin = plugin_instance
        self.main_window = plugin_instance.main_window
        self._init_ui()
        self._populate_connection_lists()
        self.populate_spider_list() # Populate initially
        self._load_auto_notification_settings()

    def _init_ui(self):
        # Recreate the Email Tab UI from DataConnectorWidget._create_email_tab
        container = self # Use self as the main container
        layout = QVBoxLayout(container) # Use self as the main layout parent
        layout.setContentsMargins(5, 5, 5, 5)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        tab_content_widget = QWidget() # Content that goes inside scroll area
        inner_layout = QVBoxLayout(tab_content_widget)
        inner_layout.addWidget(QLabel("Configure email sending & setup auto-notifications."))

        # Email Connections Group
        email_connections_group = QGroupBox("Email Connections")
        email_connections_layout = QVBoxLayout(email_connections_group)
        self.email_connections_table = QTableWidget(0, 2)
        self.email_connections_table.setHorizontalHeaderLabels(["Name", "Actions"])
        self.email_connections_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.email_connections_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.email_connections_table.verticalHeader().setVisible(False)
        email_connections_layout.addWidget(self.email_connections_table)
        add_email_button = QPushButton(QIcon.fromTheme("list-add"), "Add Email Connection")
        add_email_button.clicked.connect(self._add_email_connection)
        email_connections_layout.addWidget(add_email_button)
        inner_layout.addWidget(email_connections_group)

        # Send Manual Email Group
        send_group = QGroupBox("Send Manual Email")
        send_layout = QGridLayout(send_group)
        send_layout.addWidget(QLabel("Connection:"), 0, 0)
        self.email_connection_combo = QComboBox()
        send_layout.addWidget(self.email_connection_combo, 0, 1, 1, 2)
        send_layout.addWidget(QLabel("To*:"), 1, 0)
        self.email_to_input = QLineEdit()
        self.email_to_input.setPlaceholderText("comma, separated, emails")
        send_layout.addWidget(self.email_to_input, 1, 1, 1, 2)
        send_layout.addWidget(QLabel("Subject:"), 2, 0)
        self.email_subject_input = QLineEdit("Scrapy Notification")
        send_layout.addWidget(self.email_subject_input, 2, 1, 1, 2)
        send_layout.addWidget(QLabel("Message:"), 3, 0, Qt.AlignTop)
        self.email_message_input = QTextEdit()
        self.email_message_input.setMinimumHeight(80)
        send_layout.addWidget(self.email_message_input, 3, 1, 1, 2)
        send_layout.addWidget(QLabel("Attachment:"), 4, 0)
        attachment_widget = QWidget()
        attachment_layout = QHBoxLayout(attachment_widget)
        self.email_attachment_input = QLineEdit()
        self.email_attachment_input.setPlaceholderText("(Optional) Path to file")
        attachment_layout.addWidget(self.email_attachment_input)
        attachment_browse_button = QPushButton("Browse...")
        attachment_browse_button.clicked.connect(self._browse_email_attachment)
        attachment_layout.addWidget(attachment_browse_button)
        send_layout.addWidget(attachment_widget, 4, 1, 1, 2)
        send_email_button = QPushButton(QIcon.fromTheme("mail-send"), "Send Email")
        send_email_button.clicked.connect(self._send_email)
        send_layout.addWidget(send_email_button, 5, 0, 1, 3)
        inner_layout.addWidget(send_group)

        # Auto Notification Group
        auto_notify_group = QGroupBox("Auto Email Notification on Spider Finish")
        auto_notify_layout = QVBoxLayout(auto_notify_group)
        self.auto_notify_checkbox = QCheckBox("Enable Auto-Notification")
        self.auto_notify_checkbox.stateChanged.connect(self._update_auto_notification_state)
        auto_notify_layout.addWidget(self.auto_notify_checkbox)
        auto_notify_form = QFormLayout()
        self.auto_notify_spider_combo = QComboBox()
        self.auto_notify_spider_combo.addItem("Any Spider")
        auto_notify_form.addRow("Spider:", self.auto_notify_spider_combo)
        self.auto_notify_connection_combo = QComboBox()
        auto_notify_form.addRow("Email Connection:", self.auto_notify_connection_combo)
        self.auto_notify_recipients_input = QLineEdit()
        self.auto_notify_recipients_input.setPlaceholderText("comma, separated")
        auto_notify_form.addRow("Recipients*:", self.auto_notify_recipients_input)
        self.auto_notify_template_combo = QComboBox()
        self.auto_notify_template_combo.addItems(["Basic Summary", "Error Report Only", "Custom"])
        self.auto_notify_template_combo.currentTextChanged.connect(self._update_auto_notification_template)
        auto_notify_form.addRow("Email Template:", self.auto_notify_template_combo)
        self.auto_notify_attach_results_checkbox = QCheckBox("Attach Results(CSV)")
        auto_notify_form.addRow("", self.auto_notify_attach_results_checkbox)
        self.auto_notify_subject_input = QLineEdit("[Scrapy] {spider_name} Completed - {item_count} Items")
        auto_notify_form.addRow("Subject:", self.auto_notify_subject_input)
        auto_notify_form.addRow("Custom Msg:", QLabel(""))
        auto_notify_layout.addLayout(auto_notify_form)
        self.auto_notify_message_input = QTextEdit()
        self.auto_notify_message_input.setMinimumHeight(80)
        self.auto_notify_message_input.setPlaceholderText("Variables: {spider_name},{start_time},{finish_time},{duration},{item_count},{error_count}")
        auto_notify_layout.addWidget(self.auto_notify_message_input)
        auto_notify_layout.addSpacing(5)
        save_button_container = QHBoxLayout()
        save_button_container.addStretch()
        self.save_auto_notify_button = QPushButton("Save Auto Settings")
        self.save_auto_notify_button.clicked.connect(self._save_auto_notification_settings)
        save_button_container.addWidget(self.save_auto_notify_button)
        save_button_container.addStretch()
        auto_notify_layout.addLayout(save_button_container)
        inner_layout.addWidget(auto_notify_group)
        inner_layout.addStretch()

        scroll.setWidget(tab_content_widget)
        layout.addWidget(scroll)

    # --- UI Population & Handling ---
    def _populate_connection_lists(self):
        """Populate email connection list and dropdowns."""
        connections = self.plugin.config.get("email_connections", {})
        logger.debug(f"Populating email connections UI with: {list(connections.keys())}")
        self.email_connections_table.setRowCount(0)
        self.email_connection_combo.clear()
        self.auto_notify_connection_combo.clear()
        sorted_ids = sorted(connections.keys())

        for row, cid in enumerate(sorted_ids):
            self.email_connections_table.insertRow(row)
            name_item = QTableWidgetItem(cid)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.email_connections_table.setItem(row, 0, name_item)
            # Actions Widget
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget); actions_layout.setContentsMargins(2,2,2,2); actions_layout.setSpacing(3)
            edit_btn = QPushButton(QIcon.fromTheme("document-edit"),""); edit_btn.setToolTip("Edit"); edit_btn.clicked.connect(functools.partial(self._edit_email_connection, cid)); actions_layout.addWidget(edit_btn)
            del_btn = QPushButton(QIcon.fromTheme("edit-delete"),""); del_btn.setToolTip("Delete"); del_btn.clicked.connect(functools.partial(self._delete_email_connection, cid)); actions_layout.addWidget(del_btn)
            actions_layout.addStretch()
            self.email_connections_table.setCellWidget(row, 1, actions_widget)

        self.email_connection_combo.addItems(sorted_ids)
        self.auto_notify_connection_combo.addItems(sorted_ids)


    def populate_spider_list(self):
        """Robustly populates the spider dropdown in the auto-notify section"""
        if not hasattr(self, 'auto_notify_spider_combo'):
            logger.warning("EmailNotify: Spider dropdown not available")
            return
            
        current_selection = self.auto_notify_spider_combo.currentText()
        self.auto_notify_spider_combo.clear()
        self.auto_notify_spider_combo.addItem("Any Spider")
        
        spiders = []
        
        # Try multiple methods to find spiders
        try:
            # Method 1: Try direct project controller approach
            if self.main_window and hasattr(self.main_window, 'project_controller'):
                project_controller = self.main_window.project_controller
                logger.debug("EmailNotify: Found project_controller")
                
                # Try to find the current project name
                current_project_name = None
                
                # Try different methods to get current project
                if hasattr(self.main_window, 'current_project'):
                    current_project = self.main_window.current_project
                    if isinstance(current_project, dict) and 'name' in current_project:
                        current_project_name = current_project['name']
                    elif isinstance(current_project, str):
                        current_project_name = current_project
                    logger.debug(f"EmailNotify: Found current_project: {current_project_name}")
                    
                elif hasattr(self.main_window, 'project_combo') and hasattr(self.main_window.project_combo, 'currentText'):
                    current_project_name = self.main_window.project_combo.currentText()
                    logger.debug(f"EmailNotify: Found project from combo: {current_project_name}")
                    
                # If we found a project name, try to get its spiders
                if current_project_name:
                    try:
                        if hasattr(project_controller, 'get_project_spiders'):
                            spiders = project_controller.get_project_spiders(current_project_name)
                            logger.info(f"EmailNotify: Found {len(spiders)} spiders for project '{current_project_name}'")
                    except Exception as e:
                        logger.warning(f"EmailNotify: Error getting spiders for project '{current_project_name}': {e}")
                else:
                    logger.warning("EmailNotify: Could not determine current project name")
                    
            # Method 2: Try to find spiders via scan
            if not spiders and self.main_window and hasattr(self.main_window, 'project_controller'):
                project_controller = self.main_window.project_controller
                projects = project_controller.get_projects() if hasattr(project_controller, 'get_projects') else {}
                
                # Try to find current project
                current_project_name = None
                if hasattr(self.main_window, 'current_project'):
                    current_project = self.main_window.current_project
                    if isinstance(current_project, dict) and 'name' in current_project:
                        current_project_name = current_project['name']
                    elif isinstance(current_project, str):
                        current_project_name = current_project
                elif hasattr(self.main_window, 'project_combo') and hasattr(self.main_window.project_combo, 'currentText'):
                    current_project_name = self.main_window.project_combo.currentText()
                
                if current_project_name and current_project_name in projects:
                    project_info = projects[current_project_name]
                    project_path = project_info.get('path', '')
                    if project_path:
                        logger.debug(f"EmailNotify: Scanning for spiders in project path: {project_path}")
                        
                        # Try to find spiders directory
                        import os
                        
                        # First try standard structure: project_path/project_name/spiders
                        spiders_dir = os.path.join(project_path, current_project_name, "spiders")
                        
                        # If that doesn't exist, try just project_path/spiders
                        if not os.path.exists(spiders_dir) or not os.path.isdir(spiders_dir):
                            spiders_dir = os.path.join(project_path, "spiders")
                            
                        if os.path.exists(spiders_dir) and os.path.isdir(spiders_dir):
                            logger.debug(f"EmailNotify: Found spiders directory: {spiders_dir}")
                            
                            # Get spider files
                            try:
                                spider_files = [f for f in os.listdir(spiders_dir) 
                                            if f.endswith(".py") and f != "__init__.py"]
                                
                                # Extract spider names
                                spider_names = [os.path.splitext(f)[0] for f in spider_files]
                                if spider_names:
                                    spiders = spider_names
                                    logger.info(f"EmailNotify: Found {len(spiders)} spiders via file scan")
                            except Exception as e:
                                logger.warning(f"EmailNotify: Error scanning spider files: {e}")
        except Exception as e:
            logger.error(f"EmailNotify: Error finding spiders: {e}", exc_info=True)
        
        # Add found spiders to dropdown
        if spiders:
            for spider in sorted(spiders):
                self.auto_notify_spider_combo.addItem(str(spider))
            logger.info(f"EmailNotify: Added {len(spiders)} spiders to dropdown")
        else:
            logger.info("EmailNotify: No spiders found to add to dropdown")
        
        # Restore previous selection if possible
        if current_selection:
            index = self.auto_notify_spider_combo.findText(current_selection)
            if index >= 0:
                self.auto_notify_spider_combo.setCurrentIndex(index)

    def _add_email_connection(self): dialog = EmailConfigDialog(parent=self); self._handle_connection_dialog(dialog, "email_connections")
    def _edit_email_connection(self, cid): connections = self.plugin.config.get("email_connections",{}); dialog = EmailConfigDialog(cid, connections.get(cid), self); self._handle_connection_dialog(dialog, "email_connections", cid)
    def _delete_email_connection(self, cid): self._handle_connection_delete(cid, "email_connections", "Email", self._populate_connection_lists) # Use specific populate

    def _handle_connection_dialog(self, dialog, config_key, original_id=None):
        if dialog.exec() == QDialog.Accepted:
            new_id = dialog.connection_id; config = dialog.get_config(); connections = self.plugin.config.setdefault(config_key, {})
            if original_id and new_id != original_id:
                if new_id in connections: QMessageBox.warning(self,"Error",f"Name '{new_id}' exists."); return
                del connections[original_id]
            elif new_id in connections and not original_id: QMessageBox.warning(self,"Error",f"Name '{new_id}' exists."); return
            connections[new_id] = config; self.plugin._save_config(); self._populate_connection_lists() # Use specific populate

    def _handle_connection_delete(self, connection_id, config_key, type_name, populate_func):
         connections = self.plugin.config.setdefault(config_key, {})
         if connection_id not in connections: QMessageBox.warning(self,"Error",f"{type_name} '{connection_id}' not found."); return
         reply=QMessageBox.question(self,"Confirm",f"Delete {type_name} '{connection_id}'?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
         if reply==QMessageBox.StandardButton.Yes: del connections[connection_id]; self.plugin._save_config(); populate_func() # Call specific populate


    @Slot()
    def _browse_email_attachment(self): path, _ = QFileDialog.getOpenFileName(self, "Select Attachment"); path and self.email_attachment_input.setText(path)

    @Slot()
    def _send_email(self):
        cid = self.email_connection_combo.currentText(); cfg_key = "email_connections"
        if not cid: QMessageBox.warning(self,"Error","Select Email connection."); return
        conns = self.plugin.config.get(cfg_key,{}); cfg = conns.get(cid)
        if not cfg: QMessageBox.warning(self,"Error",f"Email connection '{cid}' not found."); return
        recipients_str = self.email_to_input.text().strip();
        if not recipients_str: QMessageBox.warning(self,"Error","Enter recipient(s)."); return
        recipients = [r.strip() for r in recipients_str.split(',') if r.strip()]
        if not recipients: QMessageBox.warning(self,"Error","Invalid recipient(s)."); return
        subject = self.email_subject_input.text().strip() or "Scrapy Notification"; message = self.email_message_input.toPlainText()
        attachment = self.email_attachment_input.text().strip() or None
        if attachment and not Path(attachment).is_file(): QMessageBox.warning(self,"Error",f"Attachment not found: {attachment}"); return
        task_data = {"email_config":cfg,"recipients":recipients,"subject":subject,"message":message,"attachment_path":attachment}
        self._run_task_with_dialog("email","Send Email",task_data) # Use renamed thread

    def _run_task_with_dialog(self, task_type, title, task_data):
        """Helper to run the Email task in a thread with a progress dialog."""
        if task_type != "email":
            logger.error("run_task_with_dialog called for non-email task in EmailNotifierWidget")
            return
            
        # Create thread but register it with the plugin
        thread = self.plugin.register_thread(EmailTaskThread(task_data))
        
        dialog = TaskRunnerDialog(task_type, title, self)
        dialog.set_thread(thread)
        thread.start()
        dialog.exec()
        
        # Create new thread
        self.task_thread = EmailTaskThread(task_data)
        
        # Connect cleanup handler
        self.task_thread.finished.connect(self._task_thread_finished)
        
        # Create and setup dialog
        dialog = TaskRunnerDialog(task_type, title, self)
        dialog.set_thread(self.task_thread)
        
        # Start thread
        self.task_thread.start()
        
        # Show dialog modally
        dialog.exec()

    def _task_thread_finished(self):
        """Handle thread cleanup when finished"""
        # Don't try to delete the thread immediately - Qt will handle deletion
        # after the thread is fully stopped
        if hasattr(self, 'task_thread') and self.task_thread:
            logger.debug("EmailNotify: Email task thread finished, scheduling cleanup")
            # Use deleteLater() to let Qt delete it safely
            self.task_thread.deleteLater()
            # Remove our reference
            self.task_thread = None


    @Slot()
    def _save_auto_notification_settings(self):
        settings = {
            "enabled": self.auto_notify_checkbox.isChecked(),
            "spider": self.auto_notify_spider_combo.currentText(),
            "connection": self.auto_notify_connection_combo.currentText(),
            "recipients": self.auto_notify_recipients_input.text().strip(),
            "template": self.auto_notify_template_combo.currentText(),
            "attach_results": self.auto_notify_attach_results_checkbox.isChecked(),
            "subject": self.auto_notify_subject_input.text().strip(),
            "message": self.auto_notify_message_input.toPlainText().strip()
        }
        if settings["enabled"] and (not settings["connection"] or not settings["recipients"]):
            QMessageBox.warning(self,"Validation Error","Auto-notify requires connection & recipients."); return
        self.plugin.config["auto_notification"] = settings; self.plugin._save_config(); QMessageBox.information(self,"Settings Saved","Auto-notification settings saved.")

    @Slot(int)
    def _update_auto_notification_state(self, state):
        enabled = bool(state); self.auto_notify_spider_combo.setEnabled(enabled); self.auto_notify_connection_combo.setEnabled(enabled); self.auto_notify_recipients_input.setEnabled(enabled); self.auto_notify_template_combo.setEnabled(enabled); self.auto_notify_attach_results_checkbox.setEnabled(enabled); self.auto_notify_subject_input.setEnabled(enabled); self.save_auto_notify_button.setEnabled(enabled); is_custom = self.auto_notify_template_combo.currentText() == "Custom"; self.auto_notify_message_input.setEnabled(enabled and is_custom)

    @Slot(str)
    def _update_auto_notification_template(self, template_name):
        templates = {
            "Basic Summary": "Spider: {spider_name}\nStarted: {start_time}\nFinished: {finish_time}\nDuration: {duration}\nItems Scraped: {item_count}\nErrors: {error_count}",
            "Error Report Only": "Spider Run Report: {spider_name}\nStatus: {'Completed with {error_count} errors' if error_count > 0 else 'Completed successfully'}\nStarted: {start_time}\nFinished: {finish_time}\nDuration: {duration}\nItems: {item_count}",
        }
        is_custom = (template_name == "Custom")
        if not is_custom and template_name in templates: self.auto_notify_message_input.setPlainText(templates[template_name])
        # Enable message edit only if enabled AND template is Custom
        self.auto_notify_message_input.setEnabled(self.auto_notify_checkbox.isChecked() and is_custom)

    def _load_auto_notification_settings(self):
        settings = self.plugin.config.get("auto_notification", DEFAULT_CONFIG["auto_notification"])
        is_enabled = settings.get("enabled", False)
        self.auto_notify_checkbox.setChecked(is_enabled)
        s_idx = self.auto_notify_spider_combo.findText(settings.get("spider", "Any Spider")); self.auto_notify_spider_combo.setCurrentIndex(s_idx if s_idx>=0 else 0)
        c_idx = self.auto_notify_connection_combo.findText(settings.get("connection", "")); self.auto_notify_connection_combo.setCurrentIndex(c_idx if c_idx>=0 else 0)
        self.auto_notify_recipients_input.setText(settings.get("recipients", ""))
        t_name = settings.get("template", "Basic Summary"); t_idx = self.auto_notify_template_combo.findText(t_name); self.auto_notify_template_combo.setCurrentIndex(t_idx if t_idx>=0 else 0)
        self.auto_notify_attach_results_checkbox.setChecked(settings.get("attach_results", False))
        self.auto_notify_subject_input.setText(settings.get("subject", DEFAULT_CONFIG["auto_notification"]["subject"]))
        if t_name == "Custom": self.auto_notify_message_input.setText(settings.get("message", ""))
        else: self._update_auto_notification_template(t_name)
        self._update_auto_notification_state(is_enabled)

    @Slot(dict)
    def handle_spider_finished(self, spider_info: dict):
        """Handle spider finished event to send auto-notification if enabled."""
        logger.info(f"EmailNotifier Widget: Handling spider_finished for {spider_info.get('spider_name')}")

        # Access the plugin's config safely
        if not hasattr(self, 'plugin') or not hasattr(self.plugin, 'config'):
            logger.error("Cannot handle spider finish: Plugin or config not available.")
            return
        auto_notify = self.plugin.config.get("auto_notification", {})

        # Check if enabled
        if not auto_notify.get("enabled", False):
            logger.debug("Auto-notify disabled in config.")
            return

        # Check if spider matches configuration
        spider_name = spider_info.get("spider_name", "Unknown Spider")
        config_spider = auto_notify.get("spider", "Any Spider")
        if config_spider != "Any Spider" and config_spider != spider_name:
            logger.debug(f"Auto-notify skip: Spider '{spider_name}' doesn't match config '{config_spider}'.")
            return

        # Get Email Connection Details
        connection_id = auto_notify.get("connection")
        if not connection_id:
            logger.error("Auto-notify error: No connection specified.")
            return
        connections = self.plugin.config.get("email_connections", {})
        connection_config = connections.get(connection_id)
        if not connection_config:
            logger.error(f"Auto-notify error: Connection '{connection_id}' not found.")
            return

        # Get Recipients
        recipients_str = auto_notify.get("recipients")
        if not recipients_str:
            logger.error("Auto-notify error: No recipients specified.")
            return
        recipients = [r.strip() for r in recipients_str.split(',') if r.strip()]
        if not recipients:
            logger.error("Auto-notify error: Recipients list empty or invalid.")
            return

        # Extract Stats and Format Variables
        item_count = spider_info.get("item_count", 0)
        status = spider_info.get("status", "unknown")
        error_count = 1 if "fail" in status or "error" in status else 0 # Simple error check
        start_time_str = spider_info.get("start_time", "")
        finish_time_str = spider_info.get("end_time", datetime.now().isoformat()) # Use current time if missing
        duration_sec = spider_info.get("duration_seconds", 0)

        # Format times safely
        start_time_fmt = "N/A"
        try:
            if start_time_str:
                start_time_dt = datetime.fromisoformat(start_time_str)
                start_time_fmt = start_time_dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError): # Catch potential errors
            logger.warning(f"Could not parse start_time for notification: {start_time_str}")

        finish_time_fmt = "N/A"
        try:
            finish_time_dt = datetime.fromisoformat(finish_time_str)
            finish_time_fmt = finish_time_dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            logger.warning(f"Could not parse finish_time for notification: {finish_time_str}")

        duration_str = "N/A"
        if isinstance(duration_sec, (int, float)) and duration_sec >= 0:
            try:
                # Use gmtime for duration formatting
                duration_str = time.strftime('%H:%M:%S', time.gmtime(duration_sec))
            except ValueError: # Handle potential large duration values
                duration_str = f"{duration_sec:.0f} seconds"
        elif duration_sec is not None: # Log if it's not a number
            logger.warning(f"Duration value is not a valid number: {duration_sec}")

        variables = {
            "spider_name": spider_name,
            "start_time": start_time_fmt,
            "finish_time": finish_time_fmt,
            "duration": duration_str,
            "item_count": item_count,
            "error_count": error_count
        }

        # Format Subject and Message
        subject_template = auto_notify.get("subject", "")
        message_template = auto_notify.get("message", "")
        subject = f"Scrapy Run: {spider_name}" # Default subject
        message = f"Spider {spider_name} finished.\nDetails:\n{variables}" # Default message
        try:
            subject = subject_template.format(**variables)
        except KeyError as e:
            logger.warning(f"Invalid placeholder in auto-notify subject template: {e}. Template: '{subject_template}'")
        except Exception as e: # Catch other formatting errors
            logger.error(f"Error formatting subject: {e}. Using default.", exc_info=True)

        try:
            message = message_template.format(**variables)
        except KeyError as e:
            logger.warning(f"Invalid placeholder in auto-notify message template: {e}. Template: '{message_template}'")
        except Exception as e: # Catch other formatting errors
            logger.error(f"Error formatting message: {e}. Using default.", exc_info=True)

        # Handle Attachment
        attachment_path = None
        output_file = spider_info.get("output_file")
        if auto_notify.get("attach_results", False):
            if output_file and Path(output_file).is_file():
                try:
                    output_path = Path(output_file)
                    data_to_attach = self._read_results_file(output_path) # Use helper
                    if data_to_attach:
                        # Use fieldnames from the *first* item assuming consistent structure
                        fieldnames = list(data_to_attach[0].keys()) if isinstance(data_to_attach, list) and data_to_attach and isinstance(data_to_attach[0], dict) else []
                        if fieldnames:
                            temp_dir = Path("temp_attachments")
                            temp_dir.mkdir(parents=True, exist_ok=True)
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            safe_spider_name = re.sub(r'\W+', '_', spider_name) # Sanitize name
                            csv_filename = f"results_{safe_spider_name}_{timestamp}.csv"
                            csv_path = temp_dir / csv_filename

                            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                                writer.writeheader()
                                writer.writerows(data_to_attach)

                            attachment_path = str(csv_path)
                            logger.info(f"Created CSV attachment for auto-notify: {attachment_path}")
                        else:
                            logger.warning("Could not determine fieldnames from results data for attachment.")
                    else:
                        logger.warning(f"Could not read results from {output_path} for attachment (empty or failed read).")
                except Exception as e:
                    logger.error(f"Failed to create CSV attachment from {output_file}: {e}", exc_info=True)
            else:
                logger.warning(f"Attach results requested, but output file path is missing or invalid: {output_file}")

        # Prepare and Run Email Task
        task_data = {
            "email_config": connection_config,
            "recipients": recipients,
            "subject": subject,
            "message": message,
            "attachment_path": attachment_path
        }

        # Clean up previous thread if it exists and is running
        if hasattr(self, 'notify_thread') and self.notify_thread:
            if self.notify_thread.isRunning():
                logger.warning("Previous auto-notify thread still running. Trying to clean up...")
                self.notify_thread.wait(500)  # Wait up to 0.5 second
                
                # If still running, force termination
                if self.notify_thread.isRunning():
                    logger.warning("Thread cleanup taking too long, forcing termination")
                    self.notify_thread.terminate()
                    self.notify_thread.wait(500)  # Wait a bit more
                
                # Clean up the old thread
                self.notify_thread.deleteLater()
                self.notify_thread = None

        # Create new thread
        self.notify_thread = self.plugin.register_thread(EmailTaskThread(task_data))
        
        # Connect signals for logging results
        self.notify_thread.log_signal.connect(
            lambda level, msg: logger.log(getattr(logging, level.upper(), logging.INFO), f"AutoNotify Email: {msg}")
        )
        self.notify_thread.result_signal.connect(
            lambda success, msg, res: logger.log(logging.INFO if success else logging.ERROR, f"AutoNotify Result: Success={success}, Msg='{msg}'")
        )
        
        # Connect finished to cleanup
        self.notify_thread.finished.connect(self._notify_thread_finished)
        
        # Start thread
        self.notify_thread.start()
        logger.info(f"Submitted auto-notification email task for spider {spider_name}.")

    def _notify_thread_finished(self):
        """Handle notify thread cleanup when finished"""
        if hasattr(self, 'notify_thread') and self.notify_thread:
            logger.debug("Auto-notify thread finished, scheduling cleanup")
            # Use deleteLater to let Qt delete it safely
            self.notify_thread.deleteLater()
            # Remove our reference
            self.notify_thread = None

    def _read_results_file(self, file_path: Path):
        """Reads JSON, JL, or CSV data from the output file."""
        data = []
        logger.debug(f"Reading results file: {file_path}")

        # Ensure file_path is valid and exists
        if not file_path or not isinstance(file_path, Path) or not file_path.is_file():
            logger.warning(f"Invalid or non-existent file path provided for reading results: {file_path}")
            return data # Return empty list if path is bad

        try:
            ext = file_path.suffix.lower()
            logger.debug(f"Detected file extension: {ext}")

            # Use 'errors=ignore' cautiously, could hide encoding issues
            with open(file_path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
                if ext == ".json":
                    loaded = json.load(f)
                    # Handle single object or list of objects
                    if isinstance(loaded, list):
                        data = loaded
                    elif isinstance(loaded, dict):
                        data = [loaded] # Wrap single object in a list
                    else:
                        logger.warning(f"JSON file {file_path} did not contain a list or object.")
                        data = []
                elif ext == ".jl":
                    data = []
                    for line_num, line in enumerate(f):
                        line = line.strip()
                        if line:
                            try:
                                data.append(json.loads(line))
                            except json.JSONDecodeError as jl_err:
                                logger.warning(f"Skipping invalid JSON line {line_num+1} in {file_path.name}: {jl_err}")
                elif ext == ".csv":
                    # Handle potential empty CSV or just header row
                    reader = csv.DictReader(f)
                    try:
                        data = list(reader)
                        if not data and reader.fieldnames: # Check if only header existed
                            logger.warning(f"CSV file {file_path.name} contains only headers or is empty.")
                        elif not reader.fieldnames: # Check if file was completely empty
                            logger.warning(f"CSV file {file_path.name} appears empty (no headers found).")
                            data = [] # Ensure data is empty list
                    except csv.Error as csv_err:
                        logger.error(f"Error reading CSV file {file_path.name}: {csv_err}", exc_info=True)
                        data = [] # Reset data on CSV error
                else:
                    logger.warning(f"Unsupported results file format for attachment: {ext}")

        except json.JSONDecodeError as json_err:
             logger.error(f"Failed to decode JSON from {file_path.name}: {json_err}", exc_info=True)
             data = [] # Reset data on error
        except Exception as e:
            logger.error(f"Error reading results file {file_path}: {e}", exc_info=True)
            data = [] # Reset data on any other error

        logger.debug(f"Read {len(data)} items from results file: {file_path.name}")
        return data

    @Slot()
    def handle_project_changed_slot(self):
        self.populate_spider_list()


# --- Signal Emitter Helper ---
class PluginSignalEmitter(QObject):
    spider_finished_signal = Signal(dict)


# --- Plugin Class ---
class Plugin(PluginBase): # NO QObject inheritance
    """
    Plugin to send email notifications manually or automatically.
    """
    def __init__(self):
        super().__init__()
        self.name = "Email Notifier"
        self.description = "Send manual or automatic email notifications on spider completion."
        self.version = "1.0.0"
        self.main_window = None
        self.notifier_tab = None
        self.config = DEFAULT_CONFIG.copy()
        self.signal_emitter = PluginSignalEmitter()
        self.active_threads = []  # Keep track of active threads to prevent GC

    def initialize(self, main_window, config=None):
        self._load_config() # Load *this* plugin's config
        if config: # Merge if passed from loader (unlikely now)
             self.config.update(config)
        super().initialize(main_window) # Pass only main_window

    def register_thread(self, thread):
        """Register a thread to prevent premature garbage collection"""
        # Clean up finished threads first
        self.active_threads = [t for t in self.active_threads if t.isRunning()]
        
        # Connect thread's finished signal to cleanup
        thread.finished.connect(lambda: self.cleanup_thread(thread))
        
        # Add to active threads list
        self.active_threads.append(thread)
        logger.debug(f"{self.name}: Registered thread, active count: {len(self.active_threads)}")
        
        return thread
    
    def cleanup_thread(self, thread):
        """Remove thread from active threads when finished"""
        if thread in self.active_threads:
            self.active_threads.remove(thread)
            logger.debug(f"{self.name}: Thread completed, active count: {len(self.active_threads)}")

    def initialize_ui(self, main_window):
        self.main_window = main_window
        # Connect project change signal
        project_list_widget = getattr(main_window, 'project_list', None)
        if project_list_widget and hasattr(project_list_widget, 'currentItemChanged'):
            project_list_widget.currentItemChanged.connect(self.handle_project_changed)
            logger.info(f"{self.name}: Connected to project_list.currentItemChanged")
        else: logger.warning(f"{self.name}: Could not find project list signal.")

        if hasattr(main_window, 'tab_widget'):
            try:
                # Create the dedicated widget, passing self (plugin instance)
                self.notifier_tab = EmailNotifierWidget(self, main_window)
                # Connect plugin signal to widget slot
                self.signal_emitter.spider_finished_signal.connect(self.notifier_tab.handle_spider_finished)
                logger.debug(f"{self.name}: Connected helper signal to widget slot.")
                # Add the tab
                icon = QIcon.fromTheme("mail-send-receive", QIcon.fromTheme("internet-mail"))
                main_window.tab_widget.addTab(self.notifier_tab, icon, "Email Notifier") # New tab name
                logger.info(f"{self.name} plugin initialized UI.")
            except Exception as e: logger.exception(f"Failed {self.name} UI init:"); QMessageBox.critical(main_window,"Plugin Error",f"Failed {self.name} init:\n{e}")
        else: logger.error(f"Could not find main window's tab_widget for {self.name}.")

    def on_spider_finished(self, spider_info, status, item_count):
        """Core hook called by PluginManager."""
        logger.info(f"{self.name} Plugin: Received on_spider_finished for {spider_info.get('spider_name')}")
        spider_info_copy = spider_info.copy()
        spider_info_copy['item_count'] = item_count
        spider_info_copy['status'] = status
        # Emit signal via helper object
        self.signal_emitter.spider_finished_signal.emit(spider_info_copy)
        logger.debug(f"{self.name}: Emitted spider_finished_signal via helper.")

    # --- Config Management specific to this plugin ---
    def _load_config(self):
        """Loads configuration from CONFIG_FILE or uses defaults."""
        # Use the specific CONFIG_FILE path for this plugin
        config_path = CONFIG_FILE
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f: loaded_config = json.load(f)
                temp_config = DEFAULT_CONFIG.copy()
                # Deep merge auto_notification if present
                if "auto_notification" in loaded_config and isinstance(loaded_config.get("auto_notification"), dict):
                     temp_config["auto_notification"].update(loaded_config["auto_notification"])
                # Overwrite/add email_connections
                temp_config["email_connections"] = loaded_config.get("email_connections", {})

                self.config = temp_config
                logger.info(f"{self.name} config loaded from {config_path}")
            except Exception as e: logger.error(f"Failed load {self.name} config: {e}"); self.config = DEFAULT_CONFIG.copy()
        else: logger.info(f"{self.name} config file not found. Using defaults."); self.config = DEFAULT_CONFIG.copy()

    def _save_config(self):
        """Saves the current configuration to CONFIG_FILE."""
        # Use the specific CONFIG_FILE path for this plugin
        config_path = CONFIG_FILE
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f: json.dump(self.config, f, indent=2)
            logger.info(f"{self.name} config saved to {config_path}")
        except Exception as e: logger.error(f"Failed save {self.name} config: {e}")

    @Slot(QtWidgets.QListWidgetItem, QtWidgets.QListWidgetItem)
    def handle_project_changed(self, current=None, previous=None):
        """Slot to update spider list in the widget when project changes."""
        logger.info(f"{self.name}: Project changed. Updating spider list.")
        if self.notifier_tab and hasattr(self.notifier_tab, 'populate_spider_list'):
            QTimer.singleShot(100, self.notifier_tab.populate_spider_list)

    # --- Settings Widget (for Preferences Dialog) ---
    def _create_settings_widget(self):
         # Provide a minimal widget for Preferences, linking to the main tab
         widget = QWidget()
         layout = QVBoxLayout(widget)
         label = QLabel(f"{self.name} settings are managed in the '{self.name}' tab.")
         label.setWordWrap(True)
         layout.addWidget(label)
         button = QPushButton(f"Go to {self.name} Tab")
         button.clicked.connect(self._go_to_plugin_tab) # Connect to helper
         layout.addWidget(button)
         layout.addStretch()
         return widget

    def _go_to_plugin_tab(self):
         """Helper to switch focus to this plugin's main tab."""
         if self.main_window and self.notifier_tab and hasattr(self.main_window, 'tab_widget'):
             index = self.main_window.tab_widget.indexOf(self.notifier_tab)
             if index != -1:
                 self.main_window.tab_widget.setCurrentIndex(index)
             else:
                 logger.warning(f"Could not find tab index for {self.name}")

    def on_app_exit(self):
        """Safely clean up threads before exiting"""
        # Wait for active threads to finish
        for thread in self.active_threads:
            if thread.isRunning():
                logger.info(f"{self.name}: Waiting for thread to finish before exit")
                thread.wait(1000)  # Wait up to 1 second per thread
                
        self._save_config()
        logger.info(f"{self.name} plugin exiting.")

        
        # Then save configuration
        self._save_config()
        logger.info(f"{self.name} plugin exiting and all threads cleaned up.")