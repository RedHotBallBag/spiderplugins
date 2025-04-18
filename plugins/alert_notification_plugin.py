# plugins/alert_notification_plugin.py
import logging
import json
import os
import threading
import queue
import smtplib
import time
import re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import subprocess
from typing import Dict, List, Any, Optional, Tuple

from PySide6 import QtWidgets, QtCore, QtGui, QtMultimedia
from PySide6.QtCore import Qt, Slot, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, 
    QCheckBox, QComboBox, QSpinBox, QLineEdit, QTabWidget,
    QPushButton, QDialog, QDialogButtonBox, QTableWidget, 
    QTableWidgetItem, QHeaderView, QMessageBox, QTextEdit,
    QListWidget, QListWidgetItem, QScrollArea, QGroupBox,
    QApplication
)

from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# ================ Constants and Configuration ================
DEFAULT_CONFIG = {
    "enabled": True,
    "notification_types": {
        "toast": True,
        "sound": True,
        "email": False,
        "desktop": True,
    },
    "alert_conditions": {
        "zero_items": True,
        "error_in_log": True,
        "connection_error": True,
        "parse_error": True,
        "non_200_status": True,
        "runtime_threshold": {
            "enabled": True,
            "max_minutes": 30
        }
    },
    "email_settings": {
        "smtp_server": "",
        "smtp_port": 587,
        "use_tls": True,
        "username": "",
        "password": "",
        "from_address": "",
        "to_addresses": [""]
    },
    "sound_settings": {
        "enabled": True,
        "volume": 70,
        "sound_file": "default"  # "default" or path to sound file
    },
    "toast_settings": {
        "duration_sec": 5,
        "position": "bottom_right"
    },
    "alert_history_max": 100,
    "blacklist_patterns": []
}

# --- Use absolute path for config ---
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = BASE_DIR / "config" / "alert_notification_plugin.json"

# ================ Toast Notification Widget ================
class ToastNotification(QWidget):
    """A toast notification widget that appears on screen."""
    
    closed = Signal()
    
    def __init__(self, title, message, level="info", duration=5, position="bottom_right", parent=None): # Add position parameter
        super().__init__(parent)
        self.parent_widget = parent
        self.level = level
        self.position = position # Store position

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._init_ui(title, message)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.close_animation)
        self.timer.setSingleShot(True)
        self.timer.start(duration * 1000)

        self.opacity = 0.0
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._update_opacity)
        self.animation_timer.start(20) # 50 fps

        # Call _set_position AFTER the UI is initialized and size is known
        # It's better to call it just before self.show() or handle resizing
        # Let's adjust size first
        self.adjustSize() # Ensure the size is calculated based on content
        self._set_position() # Now set position

        self.show()
        
    def _init_ui(self, title, message):
        # Set up the layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # Create the header
        header_layout = QHBoxLayout()
        
        # Icon based on level
        icon_label = QLabel()
        if self.level == "error":
            icon = QIcon.fromTheme("dialog-error")
            color = "#F44336"  # Red
        elif self.level == "warning":
            icon = QIcon.fromTheme("dialog-warning")
            color = "#FFC107"  # Amber
        else:  # info
            icon = QIcon.fromTheme("dialog-information")
            color = "#2196F3"  # Blue
        
        if not icon.isNull():
            pixmap = icon.pixmap(24, 24)
            icon_label.setPixmap(pixmap)
        header_layout.addWidget(icon_label)
        
        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 16px;")
        header_layout.addWidget(title_label)
        
        # Spacer
        header_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("×")
        close_btn.setFlat(True)
        close_btn.setMaximumSize(20, 20)
        close_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        close_btn.clicked.connect(self.close_animation)
        header_layout.addWidget(close_btn)
        
        layout.addLayout(header_layout)
        
        # Add a separator line
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet(f"background-color: {color};")
        layout.addWidget(separator)
        
        # Message
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("color: #333333;")
        message_label.setMinimumWidth(300)
        message_label.setMaximumWidth(400)
        layout.addWidget(message_label)
        
        # Set the background
        self.setStyleSheet("""
            ToastNotification {
                background-color: #FFFFFF;
                border: 1px solid #CCCCCC;
                border-radius: 5px;
            }
        """)
        
        # Set drop shadow
        shadow = QtWidgets.QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(2, 2)
        self.setGraphicsEffect(shadow)
    
    def _set_position(self):
        """Set the position of the notification based on self.position."""
        margin = 20 # Screen margin
        parent = self.parent() # Use parent() instead of self.parent_widget if possible for screen geometry context

        if parent:
            screen_geometry = parent.screen().availableGeometry()
        else:
            screen_geometry = QApplication.primaryScreen().availableGeometry()

        widget_size = self.size()

        x, y = 0, 0

        if self.position == "bottom_right":
            x = screen_geometry.right() - widget_size.width() - margin
            y = screen_geometry.bottom() - widget_size.height() - margin
        elif self.position == "bottom_left":
            x = screen_geometry.left() + margin
            y = screen_geometry.bottom() - widget_size.height() - margin
        elif self.position == "top_right":
            x = screen_geometry.right() - widget_size.width() - margin
            y = screen_geometry.top() + margin
        elif self.position == "top_left":
            x = screen_geometry.left() + margin
            y = screen_geometry.top() + margin
        else: # Default to bottom_right
            x = screen_geometry.right() - widget_size.width() - margin
            y = screen_geometry.bottom() - widget_size.height() - margin

        # TODO: Add logic here to handle multiple toasts stacking instead of overlapping
        # This might involve querying existing toasts and adjusting the y position.

        self.move(x, y)
    
    def _update_opacity(self):
        """Update the opacity for fade-in animation."""
        if self.opacity < 1.0:
            self.opacity += 0.05
            self.setWindowOpacity(self.opacity)
        else:
            self.animation_timer.stop()
    
    def close_animation(self):
        """Fade out the notification before closing."""
        self.animation_timer.stop()
        
        # Create fade out animation
        self.fade_out_timer = QTimer(self)
        self.fade_out_timer.timeout.connect(self._fade_out_step)
        self.fade_out_timer.start(20)
    
    def _fade_out_step(self):
        """Single step in the fade out animation."""
        if self.opacity > 0.0:
            self.opacity -= 0.05
            self.setWindowOpacity(self.opacity)
        else:
            self.fade_out_timer.stop()
            self.closed.emit()
            self.close()
            self.deleteLater()

# ================ Alert Manager Class ================
class AlertManager:
    """Manages alerts and notifications for spider issues."""
    
    def __init__(self, plugin, config=None):
        self.plugin = plugin
        self.config = config or DEFAULT_CONFIG.copy()
        self.alert_history = []
        self.sound_player = None
        self.init_sound_player()
        
        # Queue for email sending
        self.email_queue = queue.Queue()
        self.email_thread = None
        
        # Start email thread if email notifications are enabled
        if self.config["notification_types"]["email"]:
            self._start_email_thread()
    
    def init_sound_player(self):
        """Initialize the sound player."""
        try:
            self.sound_player = QtMultimedia.QSoundEffect()
            sound_file = self.config["sound_settings"]["sound_file"]
            
            # Use default sound if configured or if the specified file doesn't exist
            if sound_file == "default" or not os.path.exists(sound_file):
                # Use a default system sound based on platform
                if os.name == "nt":  # Windows
                    sound_file = "C:\\Windows\\Media\\Windows Notify.wav"
                elif os.name == "posix":  # Linux/Mac
                    possible_sounds = [
                        "/usr/share/sounds/freedesktop/stereo/complete.oga",
                        "/usr/share/sounds/freedesktop/stereo/bell.oga",
                        "/usr/share/sounds/freedesktop/stereo/alarm.oga"
                    ]
                    for ps in possible_sounds:
                        if os.path.exists(ps):
                            sound_file = ps
                            break
            
            # Set the source sound file
            if os.path.exists(sound_file):
                self.sound_player.setSource(QUrl.fromLocalFile(sound_file))
                self.sound_player.setVolume(self.config["sound_settings"]["volume"] / 100.0)
                logger.info(f"Sound player initialized with sound file: {sound_file}")
            else:
                logger.warning(f"Sound file not found: {sound_file}")
                self.sound_player = None
        except Exception as e:
            logger.error(f"Error initializing sound player: {e}")
            self.sound_player = None
    
    def _start_email_thread(self):
        """Start the email sending thread."""
        if self.email_thread and self.email_thread.is_alive():
            return  # Thread already running
            
        self.email_thread_running = True
        self.email_thread = threading.Thread(
            target=self._email_worker,
            name="AlertEmailThread",
            daemon=True
        )
        self.email_thread.start()
        logger.info("Started email notification thread")
    
    def _stop_email_thread(self):
        """Stop the email sending thread."""
        if self.email_thread and self.email_thread.is_alive():
            self.email_thread_running = False
            self.email_thread.join(timeout=2)
            logger.info("Stopped email notification thread")
    
    def _email_worker(self):
        """Background thread for sending email notifications."""
        while self.email_thread_running:
            try:
                # Get an email task from queue with a timeout
                try:
                    email_task = self.email_queue.get(timeout=2)
                except queue.Empty:
                    # No task, continue the loop
                    continue
                
                # Send the email
                self._send_email(
                    email_task["subject"],
                    email_task["message"],
                    email_task["alert_info"]
                )
                
                # Mark task as done
                self.email_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error in email worker thread: {e}")
            
            # Sleep a bit to prevent CPU thrashing on errors
            time.sleep(0.5)
    
    def _send_email(self, subject, message, alert_info):
        """Send an email notification."""
        email_settings = self.config["email_settings"]
        
        # Check if email settings are configured
        if (not email_settings["smtp_server"] or 
            not email_settings["username"] or 
            not email_settings["password"]):
            logger.warning("Email settings not configured, cannot send notification email")
            return
        
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg["From"] = email_settings["from_address"] or email_settings["username"]
            msg["To"] = ", ".join(email_settings["to_addresses"])
            msg["Subject"] = subject
            
            # Add some email styling
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; padding: 20px; }}
                    .header {{ color: #d9534f; }}
                    .details {{ margin-top: 15px; background-color: #f5f5f5; padding: 10px; border-left: 4px solid #d9534f; }}
                    .footer {{ margin-top: 20px; font-size: 12px; color: #777; }}
                    .label {{ font-weight: bold; }}
                </style>
            </head>
            <body>
                <h2 class="header">Spider Alert: {alert_info.get('spider_name', 'Unknown')}</h2>
                <p>{message}</p>
                
                <div class="details">
                    <p><span class="label">Project:</span> {alert_info.get('project_name', 'Unknown')}</p>
                    <p><span class="label">Spider:</span> {alert_info.get('spider_name', 'Unknown')}</p>
                    <p><span class="label">Alert Type:</span> {alert_info.get('alert_type', 'Unknown')}</p>
                    <p><span class="label">Time:</span> {alert_info.get('timestamp', datetime.now().isoformat())}</p>
                    <p><span class="label">Details:</span> {alert_info.get('details', 'No additional details')}</p>
                </div>
                
                <div class="footer">
                    <p>This is an automated message from Scrapy Spider Manager Alert System</p>
                </div>
            </body>
            </html>
            """
            
            # Attach HTML content
            msg.attach(MIMEText(html_content, "html"))
            
            # Connect to server and send
            smtp_server = email_settings["smtp_server"]
            smtp_port = email_settings["smtp_port"]
            use_tls = email_settings["use_tls"]
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            
            server.login(email_settings["username"], email_settings["password"])
            server.send_message(msg)
            server.quit()
            
            logger.info(f"Email notification sent: {subject}")
            
        except Exception as e:
            logger.error(f"Error sending email notification: {e}")
    
    def trigger_alert(self, alert_type, details, spider_info, level="error"):
        """
        Trigger an alert based on the configured notification types.
        
        Args:
            alert_type (str): Type of alert (e.g., "zero_items", "error_in_log")
            details (str): Details about the alert
            spider_info (dict): Information about the spider that triggered the alert
            level (str): Alert level ("info", "warning", "error")
        """
        if not self.config["enabled"]:
            logger.debug(f"Alerts disabled, not triggering: {alert_type}")
            return
        
        # Create alert info
        timestamp = datetime.now().isoformat()
        spider_name = spider_info.get("spider_name", "Unknown")
        project_name = spider_info.get("project_name", "Unknown")
        
        # Check blacklist patterns
        for pattern in self.config["blacklist_patterns"]:
            if re.search(pattern, spider_name):
                logger.info(f"Spider {spider_name} matches blacklist pattern '{pattern}', skipping alert")
                return
        
        alert_info = {
            "alert_type": alert_type,
            "timestamp": timestamp,
            "level": level,
            "spider_name": spider_name,
            "project_name": project_name,
            "details": details,
            "spider_info": spider_info
        }
        
        # Add to history
        self.alert_history.insert(0, alert_info)
        
        # Trim history if needed
        if len(self.alert_history) > self.config["alert_history_max"]:
            self.alert_history = self.alert_history[:self.config["alert_history_max"]]
        
        # Format alert message
        title = f"Spider Alert: {alert_type}"
        message = f"{project_name}/{spider_name}: {details}"
        
        # Handle each notification type
        self._handle_notification_types(title, message, alert_info, level)
    
    def _handle_notification_types(self, title, message, alert_info, level):
        """Handle all enabled notification types."""
        notification_types = self.config["notification_types"]
        
        # Show toast notification
        if notification_types["toast"]:
            self._display_toast(title, message, level)
        
        # Play sound alert
        if notification_types["sound"] and self.config["sound_settings"]["enabled"]:
            self._play_sound_alert()
        
        # Send desktop notification (if supported)
        if notification_types["desktop"]:
            self._send_desktop_notification(title, message)
        
        # Queue email notification
        if notification_types["email"]:
            self._queue_email_notification(title, message, alert_info)
    
    def _display_toast(self, title, message, level):
        """Display a toast notification."""
        try:
            parent = self.plugin.main_window if hasattr(self.plugin, "main_window") else None
            duration = self.config["toast_settings"]["duration_sec"]
            position = self.config["toast_settings"]["position"] # <<< Get position from config

            # Create and store the toast notification, passing the position
            toast = ToastNotification(title, message, level, duration, position, parent) # <<< Pass position

            # Optional active toasts management
            if hasattr(self, "active_toasts"):
                self.active_toasts.append(toast)
                toast.closed.connect(lambda t=toast: self.active_toasts.remove(t) if t in self.active_toasts else None)

            logger.debug(f"Displayed toast notification: {title}")

        except Exception as e:
            logger.error(f"Error displaying toast notification: {e}")
    
    def _play_sound_alert(self):
        """Play a sound alert."""
        if not self.sound_player:
            logger.warning("Sound player not initialized, cannot play alert sound")
            return
            
        try:
            # Set volume from config
            self.sound_player.setVolume(self.config["sound_settings"]["volume"] / 100.0)
            
            # Play the sound
            self.sound_player.play()
            logger.debug("Played alert sound")
            
        except Exception as e:
            logger.error(f"Error playing sound alert: {e}")
    
    def _send_desktop_notification(self, title, message):
        """Send a desktop notification using platform-specific methods."""
        try:
            # Windows notification (via PowerShell)
            if os.name == "nt":
                ps_script = f'powershell -command "& {{Add-Type -AssemblyName System.Windows.Forms; $notify = New-Object System.Windows.Forms.NotifyIcon; $notify.Icon = [System.Drawing.SystemIcons]::Information; $notify.Visible = $true; $notify.ShowBalloonTip(10, \'{title}\', \'{message}\', [System.Windows.Forms.ToolTipIcon]::Error)}}"'
                subprocess.Popen(ps_script, shell=True)
                logger.debug("Sent Windows desktop notification")
                
            # Linux notification (via notify-send)
            elif os.name == "posix" and os.system("which notify-send > /dev/null") == 0:
                os.system(f'notify-send "{title}" "{message}"')
                logger.debug("Sent Linux desktop notification")
                
            # macOS notification (via osascript)
            elif os.name == "posix" and os.system("which osascript > /dev/null") == 0:
                os.system(f'osascript -e \'display notification "{message}" with title "{title}"\'')
                logger.debug("Sent macOS desktop notification")
                
            else:
                logger.warning("Desktop notifications not supported on this platform")
                
        except Exception as e:
            logger.error(f"Error sending desktop notification: {e}")
    
    def _queue_email_notification(self, title, message, alert_info):
        """Queue an email notification to be sent by the background thread."""
        # Only queue if email thread is running
        if not hasattr(self, "email_thread") or not self.email_thread or not self.email_thread.is_alive():
            if self.config["notification_types"]["email"]:
                # Try to start the email thread
                self._start_email_thread()
            else:
                logger.debug("Email notifications disabled, not queuing email")
                return
        
        # Add to the queue
        self.email_queue.put({
            "subject": title,
            "message": message,
            "alert_info": alert_info
        })
        logger.debug(f"Queued email notification: {title}")

# ================ Alert Preferences Widget ================
class AlertPreferencesWidget(QWidget):
    """Widget for configuring alert preferences."""
    
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.setMinimumWidth(450)
        self._init_ui()
        self._load_settings()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        
        # Create scroll area for lots of settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        content_widget = QWidget()
        scroll_layout = QVBoxLayout(content_widget)
        
        # Main enable checkbox
        self.enable_checkbox = QCheckBox("Enable Alerts")
        self.enable_checkbox.stateChanged.connect(self._update_ui_states)
        scroll_layout.addWidget(self.enable_checkbox)
        
        # Notification types
        types_group = QGroupBox("Notification Types")
        types_layout = QVBoxLayout(types_group)
        
        self.toast_checkbox = QCheckBox("Show Toast Notifications")
        self.sound_checkbox = QCheckBox("Play Sound Alerts")
        self.email_checkbox = QCheckBox("Send Email Notifications")
        self.desktop_checkbox = QCheckBox("Send Desktop Notifications")
        
        types_layout.addWidget(self.toast_checkbox)
        types_layout.addWidget(self.sound_checkbox)
        types_layout.addWidget(self.email_checkbox)
        types_layout.addWidget(self.desktop_checkbox)
        
        scroll_layout.addWidget(types_group)
        
        # Alert conditions
        conditions_group = QGroupBox("Alert Conditions")
        conditions_layout = QVBoxLayout(conditions_group)
        
        self.zero_items_checkbox = QCheckBox("Zero Items Scraped")
        self.error_in_log_checkbox = QCheckBox("Error in Log")
        self.connection_error_checkbox = QCheckBox("Connection Error")
        self.parse_error_checkbox = QCheckBox("Parsing Error")
        self.non_200_checkbox = QCheckBox("Non-200 HTTP Status")
        
        conditions_layout.addWidget(self.zero_items_checkbox)
        conditions_layout.addWidget(self.error_in_log_checkbox)
        conditions_layout.addWidget(self.connection_error_checkbox)
        conditions_layout.addWidget(self.parse_error_checkbox)
        conditions_layout.addWidget(self.non_200_checkbox)
        
        # Runtime threshold
        runtime_layout = QHBoxLayout()
        self.runtime_checkbox = QCheckBox("Runtime Exceeds:")
        self.runtime_spinner = QSpinBox()
        self.runtime_spinner.setRange(1, 1440)  # 1 min to 24 hours
        self.runtime_spinner.setSuffix(" minutes")
        runtime_layout.addWidget(self.runtime_checkbox)
        runtime_layout.addWidget(self.runtime_spinner)
        runtime_layout.addStretch()
        
        conditions_layout.addLayout(runtime_layout)
        scroll_layout.addWidget(conditions_group)
        
        # Notification settings tabs
        settings_tabs = QTabWidget()
        
        # Sound settings tab
        sound_tab = QWidget()
        sound_layout = QVBoxLayout(sound_tab)
        
        # Sound volume
        sound_volume_layout = QHBoxLayout()
        sound_volume_layout.addWidget(QLabel("Volume:"))
        self.volume_slider = QSpinBox()
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setSuffix("%")
        sound_volume_layout.addWidget(self.volume_slider)
        sound_volume_layout.addStretch()
        
        # Sound file selection
        sound_file_layout = QHBoxLayout()
        sound_file_layout.addWidget(QLabel("Sound File:"))
        self.sound_file_input = QLineEdit()
        self.sound_file_input.setPlaceholderText("Leave empty for default")
        sound_file_layout.addWidget(self.sound_file_input)
        
        sound_browse_btn = QPushButton("Browse")
        sound_browse_btn.clicked.connect(self._browse_sound_file)
        sound_file_layout.addWidget(sound_browse_btn)
        
        sound_test_btn = QPushButton("Test Sound")
        sound_test_btn.clicked.connect(self._test_sound)
        
        sound_layout.addLayout(sound_volume_layout)
        sound_layout.addLayout(sound_file_layout)
        sound_layout.addWidget(sound_test_btn)
        sound_layout.addStretch()
        
        # Email settings tab
        email_tab = QWidget()
        email_layout = QFormLayout(email_tab)
        
        self.smtp_server_input = QLineEdit()
        self.smtp_port_spinner = QSpinBox()
        self.smtp_port_spinner.setRange(1, 65535)
        self.smtp_port_spinner.setValue(587)
        
        self.smtp_tls_checkbox = QCheckBox("Use TLS")
        self.smtp_username_input = QLineEdit()
        self.smtp_password_input = QLineEdit()
        self.smtp_password_input.setEchoMode(QLineEdit.Password)
        
        self.from_address_input = QLineEdit()
        self.to_addresses_input = QLineEdit()
        self.to_addresses_input.setPlaceholderText("Comma-separated email addresses")
        
        email_layout.addRow("SMTP Server:", self.smtp_server_input)
        email_layout.addRow("SMTP Port:", self.smtp_port_spinner)
        email_layout.addRow("", self.smtp_tls_checkbox)
        email_layout.addRow("Username:", self.smtp_username_input)
        email_layout.addRow("Password:", self.smtp_password_input)
        email_layout.addRow("From Address:", self.from_address_input)
        email_layout.addRow("To Addresses:", self.to_addresses_input)
        
        # Test email button
        email_test_layout = QHBoxLayout()
        email_test_btn = QPushButton("Test Email")
        email_test_btn.clicked.connect(self._test_email)
        email_test_layout.addStretch()
        email_test_layout.addWidget(email_test_btn)
        email_layout.addRow("", email_test_layout)
        
        # Toast settings tab
        toast_tab = QWidget()
        toast_layout = QFormLayout(toast_tab)
        
        self.toast_duration_spinner = QSpinBox()
        self.toast_duration_spinner.setRange(1, 60)
        self.toast_duration_spinner.setValue(5)
        self.toast_duration_spinner.setSuffix(" seconds")
        
        self.toast_position_combo = QComboBox()
        self.toast_position_combo.addItems([
            "Bottom Right", "Bottom Left", "Top Right", "Top Left"
        ])
        
        toast_layout.addRow("Duration:", self.toast_duration_spinner)
        toast_layout.addRow("Position:", self.toast_position_combo)
        
        # Test toast button
        toast_test_layout = QHBoxLayout()
        toast_test_btn = QPushButton("Test Toast")
        toast_test_btn.clicked.connect(self._test_toast)
        toast_test_layout.addStretch()
        toast_test_layout.addWidget(toast_test_btn)
        toast_layout.addRow("", toast_test_layout)
        
        # Blacklist tab
        blacklist_tab = QWidget()
        blacklist_layout = QVBoxLayout(blacklist_tab)
        
        blacklist_label = QLabel("Blacklist patterns (regex) for spiders that should not trigger alerts:")
        blacklist_layout.addWidget(blacklist_label)
        
        self.blacklist_list = QListWidget()
        blacklist_layout.addWidget(self.blacklist_list)
        
        blacklist_buttons = QHBoxLayout()
        
        add_blacklist_btn = QPushButton("Add")
        add_blacklist_btn.clicked.connect(self._add_blacklist_pattern)
        blacklist_buttons.addWidget(add_blacklist_btn)
        
        remove_blacklist_btn = QPushButton("Remove")
        remove_blacklist_btn.clicked.connect(self._remove_blacklist_pattern)
        blacklist_buttons.addWidget(remove_blacklist_btn)
        
        blacklist_layout.addLayout(blacklist_buttons)
        
        # Add tabs
        settings_tabs.addTab(sound_tab, "Sound")
        settings_tabs.addTab(email_tab, "Email")
        settings_tabs.addTab(toast_tab, "Toast")
        settings_tabs.addTab(blacklist_tab, "Blacklist")
        
        scroll_layout.addWidget(settings_tabs)
        
        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save_settings)
        scroll_layout.addWidget(save_btn)
        
        # Set the scroll widget
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)
    
    def _update_ui_states(self):
        """Update UI component enabled states based on current selections."""
        enabled = self.enable_checkbox.isChecked()
        
        # Enable/disable notification type checkboxes
        self.toast_checkbox.setEnabled(enabled)
        self.sound_checkbox.setEnabled(enabled)
        self.email_checkbox.setEnabled(enabled)
        self.desktop_checkbox.setEnabled(enabled)
        
        # Enable/disable alert condition checkboxes
        self.zero_items_checkbox.setEnabled(enabled)
        self.error_in_log_checkbox.setEnabled(enabled)
        self.connection_error_checkbox.setEnabled(enabled)
        self.parse_error_checkbox.setEnabled(enabled)
        self.non_200_checkbox.setEnabled(enabled)
        self.runtime_checkbox.setEnabled(enabled)
        self.runtime_spinner.setEnabled(enabled and self.runtime_checkbox.isChecked())
    
    def _load_settings(self):
        """Load settings from plugin configuration."""
        config = self.plugin.config
        
        # Main enable setting
        self.enable_checkbox.setChecked(config["enabled"])
        
        # Notification types
        self.toast_checkbox.setChecked(config["notification_types"]["toast"])
        self.sound_checkbox.setChecked(config["notification_types"]["sound"])
        self.email_checkbox.setChecked(config["notification_types"]["email"])
        self.desktop_checkbox.setChecked(config["notification_types"]["desktop"])
        
        # Alert conditions
        self.zero_items_checkbox.setChecked(config["alert_conditions"]["zero_items"])
        self.error_in_log_checkbox.setChecked(config["alert_conditions"]["error_in_log"])
        self.connection_error_checkbox.setChecked(config["alert_conditions"]["connection_error"])
        self.parse_error_checkbox.setChecked(config["alert_conditions"]["parse_error"])
        self.non_200_checkbox.setChecked(config["alert_conditions"]["non_200_status"])
        
        # Runtime threshold
        runtime_threshold = config["alert_conditions"]["runtime_threshold"]
        self.runtime_checkbox.setChecked(runtime_threshold["enabled"])
        self.runtime_spinner.setValue(runtime_threshold["max_minutes"])
        
        # Sound settings
        self.volume_slider.setValue(config["sound_settings"]["volume"])
        if config["sound_settings"]["sound_file"] != "default":
            self.sound_file_input.setText(config["sound_settings"]["sound_file"])
        
        # Email settings
        email_settings = config["email_settings"]
        self.smtp_server_input.setText(email_settings["smtp_server"])
        self.smtp_port_spinner.setValue(email_settings["smtp_port"])
        self.smtp_tls_checkbox.setChecked(email_settings["use_tls"])
        self.smtp_username_input.setText(email_settings["username"])
        self.smtp_password_input.setText(email_settings["password"])
        self.from_address_input.setText(email_settings["from_address"])
        self.to_addresses_input.setText(", ".join(email_settings["to_addresses"]))
        
        # Toast settings
        self.toast_duration_spinner.setValue(config["toast_settings"]["duration_sec"])
        
        position = config["toast_settings"]["position"]
        position_index = 0  # Default to Bottom Right
        if position == "bottom_left":
            position_index = 1
        elif position == "top_right":
            position_index = 2
        elif position == "top_left":
            position_index = 3
        self.toast_position_combo.setCurrentIndex(position_index)
        
        # Blacklist patterns
        self.blacklist_list.clear()
        for pattern in config["blacklist_patterns"]:
            self.blacklist_list.addItem(pattern)
        
        # Update enabled states
        self._update_ui_states()
    
    def _browse_sound_file(self):
        """Open file dialog to select a sound file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Sound File", "", "Sound Files (*.wav *.mp3 *.ogg);;All Files (*)"
        )
        
        if file_path:
            self.sound_file_input.setText(file_path)
    
    def _test_sound(self):
        """Test the selected sound."""
        try:
            # Create a temporary sound player
            sound_player = QtMultimedia.QSoundEffect()
            
            # Get sound file
            sound_file = self.sound_file_input.text()
            if not sound_file:
                # Use default sound based on platform
                if os.name == "nt":  # Windows
                    sound_file = "C:\\Windows\\Media\\Windows Notify.wav"
                elif os.name == "posix":  # Linux/Mac
                    possible_sounds = [
                        "/usr/share/sounds/freedesktop/stereo/complete.oga",
                        "/usr/share/sounds/freedesktop/stereo/bell.oga",
                        "/usr/share/sounds/freedesktop/stereo/alarm.oga"
                    ]
                    for ps in possible_sounds:
                        if os.path.exists(ps):
                            sound_file = ps
                            break
            
            # Set the source and volume
            if os.path.exists(sound_file):
                sound_player.setSource(QUrl.fromLocalFile(sound_file))
                sound_player.setVolume(self.volume_slider.value() / 100.0)
                sound_player.play()
                QMessageBox.information(self, "Sound Test", f"Playing sound: {sound_file}")
            else:
                QMessageBox.warning(self, "Sound Test", f"Sound file not found: {sound_file}")
                
        except Exception as e:
            QMessageBox.critical(self, "Sound Test Error", f"Error testing sound: {e}")
    
    def _test_email(self):
        """Test email settings."""
        # Get email settings from the form
        smtp_server = self.smtp_server_input.text()
        smtp_port = self.smtp_port_spinner.value()
        use_tls = self.smtp_tls_checkbox.isChecked()
        username = self.smtp_username_input.text()
        password = self.smtp_password_input.text()
        from_address = self.from_address_input.text() or username
        to_addresses = [email.strip() for email in self.to_addresses_input.text().split(",") if email.strip()]
        
        # Check required fields
        if not smtp_server or not smtp_port or not username or not password:
            QMessageBox.warning(self, "Missing Settings", 
                "Please fill in all required email settings (server, port, username, password).")
            return
        
        if not to_addresses:
            QMessageBox.warning(self, "Missing Settings", 
                "Please provide at least one recipient email address.")
            return
        
        # Create a progress dialog
        progress = QtWidgets.QProgressDialog("Sending test email...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Email Test")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        # Create a thread for sending the email
        email_thread = threading.Thread(
            target=self._send_test_email,
            args=(smtp_server, smtp_port, use_tls, username, password, from_address, to_addresses),
            daemon=True
        )
        
        # Update progress
        def update_progress():
            progress.setValue(25)
            QApplication.processEvents()
        
        # Show result
        def show_result(success, message):
            progress.setValue(100)
            if success:
                QMessageBox.information(self, "Email Test", message)
            else:
                QMessageBox.critical(self, "Email Test Error", message)
        
        # Start the thread
        email_thread.start()
        
        # Update progress
        QTimer.singleShot(500, update_progress)
        
        # Show the progress dialog
        progress.exec_()
        
        # Check if user canceled
        if progress.wasCanceled():
            # We can't really cancel the email thread, but we can close the dialog
            QMessageBox.information(self, "Email Test", "Test email sending was canceled.")
            return
        
    def _send_test_email(self, smtp_server, smtp_port, use_tls, username, password, 
                        from_address, to_addresses):
        """Send a test email in a separate thread."""
        try:
            # Create the email
            msg = MIMEMultipart()
            msg["From"] = from_address
            msg["To"] = ", ".join(to_addresses)
            msg["Subject"] = "Test Email from Scrapy Spider Manager Alert System"
            
            # Add some HTML content
            html_content = """
            <html>
            <head>
                <style>
                    body { font-family: Arial, sans-serif; padding: 20px; }
                    .header { color: #2196F3; }
                    .content { margin-top: 15px; }
                    .footer { margin-top: 20px; font-size: 12px; color: #777; }
                </style>
            </head>
            <body>
                <h2 class="header">Test Email</h2>
                <div class="content">
                    <p>This is a test email from the Scrapy Spider Manager Alert System.</p>
                    <p>If you're receiving this email, your email notification settings are working correctly.</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from Scrapy Spider Manager Alert System</p>
                    <p>Sent at: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
                </div>
            </body>
            </html>
            """
            
            # Attach the HTML content
            msg.attach(MIMEText(html_content, "html"))
            
            # Connect to the server
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            
            # Login and send
            server.login(username, password)
            server.send_message(msg)
            server.quit()
            
            # Update UI from main thread
            QtCore.QMetaObject.invokeMethod(
                self, "show_test_email_result", 
                Qt.QueuedConnection,
                QtCore.Q_ARG(bool, True),
                QtCore.Q_ARG(str, f"Test email sent successfully to {', '.join(to_addresses)}")
            )
            
        except Exception as e:
            # Update UI from main thread
            QtCore.QMetaObject.invokeMethod(
                self, "show_test_email_result", 
                Qt.QueuedConnection,
                QtCore.Q_ARG(bool, False),
                QtCore.Q_ARG(str, f"Error sending test email: {str(e)}")
            )
    
    @Slot(bool, str)
    def show_test_email_result(self, success, message):
        """Show the result of the test email send operation."""
        if success:
            QMessageBox.information(self, "Email Test", message)
        else:
            QMessageBox.critical(self, "Email Test Error", message)
    
    def _test_toast(self):
        """Test the toast notification."""
        try:
            # Get duration from spinner
            duration = self.toast_duration_spinner.value()
            
            # Create and show a test toast
            toast = ToastNotification(
                "Test Notification",
                "This is a test toast notification from the Alert System.",
                "info",
                duration,
                self.plugin.main_window
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Toast Test Error", f"Error testing toast notification: {e}")
    
    def _add_blacklist_pattern(self):
        """Add a new blacklist pattern."""
        pattern, ok = QtWidgets.QInputDialog.getText(
            self, "Add Blacklist Pattern", 
            "Enter a regex pattern for spiders to ignore:\n(e.g., 'test_.*' to ignore all spiders starting with 'test_')"
        )
        
        if ok and pattern:
            # Validate the regex
            try:
                re.compile(pattern)
                self.blacklist_list.addItem(pattern)
            except re.error as e:
                QMessageBox.critical(self, "Invalid Regex", f"Invalid regular expression pattern: {e}")
    
    def _remove_blacklist_pattern(self):
        """Remove the selected blacklist pattern."""
        selected_items = self.blacklist_list.selectedItems()
        for item in selected_items:
            self.blacklist_list.takeItem(self.blacklist_list.row(item))
    
    def _save_settings(self):
        """Save settings to the plugin configuration."""
        # Create a new config dict
        config = {
            "enabled": self.enable_checkbox.isChecked(),
            "notification_types": {
                "toast": self.toast_checkbox.isChecked(),
                "sound": self.sound_checkbox.isChecked(),
                "email": self.email_checkbox.isChecked(),
                "desktop": self.desktop_checkbox.isChecked(),
            },
            "alert_conditions": {
                "zero_items": self.zero_items_checkbox.isChecked(),
                "error_in_log": self.error_in_log_checkbox.isChecked(),
                "connection_error": self.connection_error_checkbox.isChecked(),
                "parse_error": self.parse_error_checkbox.isChecked(),
                "non_200_status": self.non_200_checkbox.isChecked(),
                "runtime_threshold": {
                    "enabled": self.runtime_checkbox.isChecked(),
                    "max_minutes": self.runtime_spinner.value()
                }
            },
            "email_settings": {
                "smtp_server": self.smtp_server_input.text(),
                "smtp_port": self.smtp_port_spinner.value(),
                "use_tls": self.smtp_tls_checkbox.isChecked(),
                "username": self.smtp_username_input.text(),
                "password": self.smtp_password_input.text(),
                "from_address": self.from_address_input.text(),
                "to_addresses": [email.strip() for email in self.to_addresses_input.text().split(",") if email.strip()]
            },
            "sound_settings": {
                "enabled": self.sound_checkbox.isChecked(), # Use the checkbox state directly
                "volume": self.volume_slider.value(),
                "sound_file": self.sound_file_input.text() or "default"
            },
            "toast_settings": {
                "duration_sec": self.toast_duration_spinner.value(),
                "position": self._get_position_key(self.toast_position_combo.currentIndex())
            },
            # Preserve the existing history max value unless configured elsewhere
            "alert_history_max": self.plugin.config.get("alert_history_max", DEFAULT_CONFIG["alert_history_max"]), # <<< FIX HERE
            "blacklist_patterns": [self.blacklist_list.item(i).text()
                                for i in range(self.blacklist_list.count())]
        }

        # Update plugin config
        self.plugin.config = config

        # Save to disk
        self.plugin._save_config()

        # Reinitialize the alert manager
        self.plugin._init_alert_manager()

        # Show success message
        QMessageBox.information(self, "Settings Saved", "Alert settings have been saved.")
        
    def _get_position_key(self, position_index):
        """Convert position index to position key."""
        if position_index == 1:
            return "bottom_left"
        elif position_index == 2:
            return "top_right"
        elif position_index == 3:
            return "top_left"
        else:
            return "bottom_right"  # Default


# ================ Alert History Widget ================
class AlertHistoryWidget(QWidget):
    """Widget for displaying alert history."""
    
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.setMinimumWidth(500)
        self._init_ui()
    
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QVBoxLayout(self)
        
        # Toolbar
        toolbar = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_history)
        toolbar.addWidget(refresh_btn)
        
        clear_btn = QPushButton("Clear History")
        clear_btn.clicked.connect(self._clear_history)
        toolbar.addWidget(clear_btn)
        
        toolbar.addStretch()
        
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_history)
        toolbar.addWidget(export_btn)
        
        layout.addLayout(toolbar)
        
        # Alert history table
        self.alert_table = QTableWidget()
        self.alert_table.setColumnCount(5)
        self.alert_table.setHorizontalHeaderLabels([
            "Time", "Spider", "Type", "Level", "Details"
        ])
        self.alert_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.alert_table.verticalHeader().setVisible(False)
        self.alert_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.alert_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.alert_table.setAlternatingRowColors(True)
        self.alert_table.setSortingEnabled(True)  # Allow sorting by columns
        
        layout.addWidget(self.alert_table)
        
        # Load initial history
        self.refresh_history()

    
    def refresh_history(self):
        """Refresh the alert history table."""
        if not hasattr(self.plugin, "alert_manager"):
            logger.warning("Alert manager not initialized.")
            return
            
        # Get history from the alert manager
        history = self.plugin.alert_manager.alert_history
        
        # Clear the table
        self.alert_table.setRowCount(0)
        
        # Add alerts to the table
        for i, alert in enumerate(history):
            row = self.alert_table.rowCount()
            self.alert_table.insertRow(row)
            
            # Format timestamp
            timestamp = alert.get("timestamp", "")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    formatted_time = timestamp
            else:
                formatted_time = "Unknown"
            
            # Set table items
            time_item = QTableWidgetItem(formatted_time)
            time_item.setData(Qt.UserRole, timestamp)  # Store original for sorting
            self.alert_table.setItem(row, 0, time_item)
            
            # Spider name (project/spider)
            project = alert.get("project_name", "")
            spider = alert.get("spider_name", "Unknown")
            spider_text = f"{project}/{spider}" if project else spider
            self.alert_table.setItem(row, 1, QTableWidgetItem(spider_text))
            
            # Alert type
            self.alert_table.setItem(row, 2, QTableWidgetItem(alert.get("alert_type", "Unknown")))
            
            # Level with appropriate color
            level = alert.get("level", "info")
            level_item = QTableWidgetItem(level.upper())
            if level == "error":
                level_item.setForeground(QColor("#F44336"))  # Red
            elif level == "warning":
                level_item.setForeground(QColor("#FFC107"))  # Amber
            else:
                level_item.setForeground(QColor("#2196F3"))  # Blue
            self.alert_table.setItem(row, 3, level_item)
            
            # Details
            self.alert_table.setItem(row, 4, QTableWidgetItem(alert.get("details", "")))
            
            # Store the full alert data
            for col in range(5):
                self.alert_table.item(row, col).setData(Qt.UserRole + 1, alert)
        
        # Resize columns to content
        self.alert_table.resizeColumnsToContents()
        
        # Set row count label
        self.alert_table.setToolTip(f"Alert History: {self.alert_table.rowCount()} alerts")
    
    def _clear_history(self):
        """Clear the alert history."""
        reply = QMessageBox.question(
            self, "Clear History",
            "Are you sure you want to clear the alert history?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Clear the history in the alert manager
            if hasattr(self.plugin, "alert_manager"):
                self.plugin.alert_manager.alert_history = []
                
                # Refresh the table
                self.refresh_history()
                
                QMessageBox.information(self, "History Cleared", "Alert history has been cleared.")
    
    def _export_history(self):
        """Export the alert history to a file."""
        file_path, file_filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Alert History",
            "",
            "CSV Files (*.csv);;JSON Files (*.json);;HTML Files (*.html);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Get history from the alert manager
            if not hasattr(self.plugin, "alert_manager"):
                QMessageBox.warning(self, "Export Error", "Alert manager not initialized.")
                return
                
            history = self.plugin.alert_manager.alert_history
            
            # Determine export format from file extension
            if file_path.lower().endswith(".csv"):
                self._export_to_csv(file_path, history)
            elif file_path.lower().endswith(".json"):
                self._export_to_json(file_path, history)
            elif file_path.lower().endswith(".html"):
                self._export_to_html(file_path, history)
            else:
                # Default to CSV
                if not file_path.lower().endswith(".csv"):
                    file_path += ".csv"
                self._export_to_csv(file_path, history)
            
            QMessageBox.information(
                self, "Export Successful",
                f"Alert history exported to:\n{file_path}"
            )
            
        except Exception as e:
            QMessageBox.critical(
                self, "Export Error",
                f"Error exporting alert history: {e}"
            )
    
    def _export_to_csv(self, file_path, history):
        """Export alert history to CSV file."""
        import csv
        
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow([
                "Timestamp", "Project", "Spider", "Alert Type", 
                "Level", "Details"
            ])
            
            # Write data
            for alert in history:
                timestamp = alert.get("timestamp", "")
                project = alert.get("project_name", "")
                spider = alert.get("spider_name", "Unknown")
                alert_type = alert.get("alert_type", "Unknown")
                level = alert.get("level", "info")
                details = alert.get("details", "")
                
                writer.writerow([timestamp, project, spider, alert_type, level, details])
    
    def _export_to_json(self, file_path, history):
        """Export alert history to JSON file."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    
    def _export_to_html(self, file_path, history):
        """Export alert history to HTML file."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Scrapy Spider Manager - Alert History</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                h1 { color: #2196F3; }
                table { width: 100%; border-collapse: collapse; }
                th { background-color: #f2f2f2; text-align: left; padding: 8px; }
                td { padding: 8px; border-bottom: 1px solid #ddd; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .error { color: #F44336; }
                .warning { color: #FFC107; }
                .info { color: #2196F3; }
                .footer { margin-top: 20px; font-size: 12px; color: #777; }
            </style>
        </head>
        <body>
            <h1>Scrapy Spider Manager - Alert History</h1>
            <p>Export generated on: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + """</p>
            <table>
                <tr>
                    <th>Time</th>
                    <th>Project</th>
                    <th>Spider</th>
                    <th>Alert Type</th>
                    <th>Level</th>
                    <th>Details</th>
                </tr>
        """
        
        for alert in history:
            timestamp = alert.get("timestamp", "")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    formatted_time = timestamp
            else:
                formatted_time = "Unknown"
                
            project = alert.get("project_name", "")
            spider = alert.get("spider_name", "Unknown")
            alert_type = alert.get("alert_type", "Unknown")
            level = alert.get("level", "info")
            details = alert.get("details", "")
            
            level_class = level
            
            html += f"""
                <tr>
                    <td>{formatted_time}</td>
                    <td>{project}</td>
                    <td>{spider}</td>
                    <td>{alert_type}</td>
                    <td class="{level_class}">{level.upper()}</td>
                    <td>{details}</td>
                </tr>
            """
        
        html += """
            </table>
            <div class="footer">
                <p>Generated by Scrapy Spider Manager Alert System</p>
            </div>
        </body>
        </html>
        """
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html)


# ================ Main Plugin Class ================
class Plugin(PluginBase):
    """
    Alert Notification Plugin for Scrapy Spider Manager.
    Provides alerts for spider issues via toast, sound, email, and more.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Alert Notifications"
        self.description = "Provides alerts for spider issues via toast, sound, email, and more"
        self.version = "1.0.0"
        self.main_window = None
        self.alert_tab = None
        self.alert_manager = None
        self.config = DEFAULT_CONFIG.copy()
        
        # Load configuration
        self._load_config()
    
    def initialize(self, main_window, config=None):
        logger.debug("Alert Notification Plugin: initialize method called")
        """Initialize the plugin."""
        self.main_window = main_window
        
        # Update config if provided
        if config:
            self.config.update(config)
        
        # Initialize alert manager
        self._init_alert_manager()
        logger.debug("Alert Notification Plugin: initialization complete")
        super().initialize(main_window, config)
    
    def _init_alert_manager(self):
        """Initialize the alert manager."""
        # Stop any existing email thread
        if hasattr(self, "alert_manager") and self.alert_manager:
            # Stop the email thread if running
            if hasattr(self.alert_manager, "_stop_email_thread"):
                self.alert_manager._stop_email_thread()
        
        # Create a new alert manager
        self.alert_manager = AlertManager(self, self.config)
        logger.info("Alert Notification Manager initialized")
    
    def _load_config(self):
        """Load configuration from file."""
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                
                # Update config with loaded values, preserving defaults for missing keys
                self._update_config_recursive(self.config, loaded_config)
                
                logger.info(f"Loaded Alert Notification Plugin configuration from {CONFIG_PATH}")
            except Exception as e:
                logger.error(f"Error loading Alert Notification Plugin configuration: {e}")
        else:
            logger.info(f"Alert Notification Plugin configuration file {CONFIG_PATH} not found, using defaults")
            self._save_config()  # Save default config
    
    def _update_config_recursive(self, target_dict, source_dict):
        """
        Recursively update a nested dictionary, preserving default values for missing keys.
        """
        for key, value in source_dict.items():
            if key in target_dict:
                if isinstance(value, dict) and isinstance(target_dict[key], dict):
                    # Recursively update nested dictionaries
                    self._update_config_recursive(target_dict[key], value)
                else:
                    # Update value
                    target_dict[key] = value
    
    def _save_config(self):
        """Save configuration to file."""
        try:
            # Ensure directory exists
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
                
            logger.info(f"Saved Alert Notification Plugin configuration to {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Error saving Alert Notification Plugin configuration: {e}")
    
    def initialize_ui(self, main_window):
        """Initialize the UI components."""
        self.main_window = main_window
        
        # Create alert tab with multiple tabs inside
        if hasattr(main_window, "tab_widget"):
            alert_tab = QWidget()
            
            # Create tab layout
            layout = QVBoxLayout(alert_tab)
            
            # Create sub-tabs
            tab_widget = QTabWidget()
            
            # Create alert history tab
            self.history_widget = AlertHistoryWidget(self)
            tab_widget.addTab(self.history_widget, "Alert History")
            
            # Create preferences tab
            self.preferences_widget = AlertPreferencesWidget(self)
            tab_widget.addTab(self.preferences_widget, "Alert Settings")
            
            layout.addWidget(tab_widget)
            
            # Add the tab to main window
            icon = QIcon.fromTheme("dialog-warning")
            main_window.tab_widget.addTab(alert_tab, icon, "Alerts")
            
            logger.info("Alert Notification Plugin UI initialized")
        else:
            logger.error("Could not find main window's tab_widget")
    

    def on_spider_started(self, spider_info):
        """Triggered when a spider starts running."""
        logger.debug(f"Alert plugin: on_spider_started called for spider {spider_info.get('spider_name')}")
        # We generally don't trigger alerts on start, but you could add specific start alerts here

    def on_spider_finished(self, spider_info, status, item_count):
        """Triggered when a spider finishes running."""
        logger.debug(f"Alert plugin: on_spider_finished called for spider {spider_info.get('spider_name')} with status {status} and {item_count} items")
        
        # Check for zero items alert condition
        if item_count == 0 and self.config["alert_conditions"]["zero_items"]:
            self.alert_manager.trigger_alert(
                "zero_items",
                f"Spider completed with 0 items scraped",
                spider_info,
                "warning"
            )
            
        # Check for error status
        if "error" in status.lower() or "fail" in status.lower():
            if self.config["alert_conditions"]["error_in_log"]:
                self.alert_manager.trigger_alert(
                    "error_in_log",
                    f"Spider failed with status: {status}",
                    spider_info,
                    "error"
                )
        
        # If you're monitoring spider run time:
        run_time_condition = self.config["alert_conditions"]["runtime_threshold"]
        if run_time_condition["enabled"] and "start_time" in spider_info and "end_time" in spider_info:
            try:
                start_time = datetime.fromisoformat(spider_info["start_time"])
                end_time = datetime.fromisoformat(spider_info["end_time"])
                duration_minutes = (end_time - start_time).total_seconds() / 60
                
                if duration_minutes > run_time_condition["max_minutes"]:
                    self.alert_manager.trigger_alert(
                        "runtime_exceeded",
                        f"Spider run took {duration_minutes:.1f} minutes (exceeds threshold of {run_time_condition['max_minutes']} minutes)",
                        spider_info,
                        "warning"
                    )
            except (ValueError, KeyError, TypeError) as e:
                logger.error(f"Error calculating spider duration: {e}")

    def process_log_entry(self, log_entry, spider_info):
        """Process a log entry and trigger alerts for error patterns."""
        if not self.config["enabled"]:
            return
        
        # Skip if we don't have alert manager initialized
        if not hasattr(self, "alert_manager") or not self.alert_manager:
            return
        
        # Skip non-error logs if we're only concerned with errors
        if "error" not in log_entry.lower() and "exception" not in log_entry.lower():
            return
        
        # Check for connection errors
        if (self.config["alert_conditions"]["connection_error"] and 
            ("connection error" in log_entry.lower() or 
            "connectionerror" in log_entry.lower() or
            "timeout" in log_entry.lower())):
            
            self.alert_manager.trigger_alert(
                "connection_error",
                f"Connection error detected: {log_entry[:150]}...",
                spider_info,
                "error"
            )
        
        # Check for parsing errors
        elif (self.config["alert_conditions"]["parse_error"] and 
            ("parse error" in log_entry.lower() or 
            "parseerror" in log_entry.lower() or
            "valueerror" in log_entry.lower())):
            
            self.alert_manager.trigger_alert(
                "parse_error",
                f"Parsing error detected: {log_entry[:150]}...",
                spider_info,
                "error"
            )