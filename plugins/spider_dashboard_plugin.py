import logging
import sys
import json
from pathlib import Path
from datetime import datetime

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QColor, QDesktopServices
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, Slot, QUrl

# Import Plugin Base & potentially other app components
from app.plugin_base import PluginBase
# We might need access to controllers/plugins via main_window, handled carefully

logger = logging.getLogger(__name__)

# --- Helper Functions ---
def create_table_item(text, editable=False, tooltip=None):
    """Creates a standard QTableWidgetItem."""
    item = QtWidgets.QTableWidgetItem(str(text))
    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    if tooltip:
        item.setToolTip(tooltip)
    return item

def format_timestamp(iso_timestamp_str):
    """Formats an ISO timestamp string nicely, returns 'N/A' on error."""
    if not iso_timestamp_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_timestamp_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return "Invalid Date"

# --- Main Dashboard Widget ---
class SpiderDashboardWidget(QtWidgets.QWidget):
    """The main widget for the Spider Dashboard tab."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.current_project_data = None
        self.current_spider_name = None
        self.analytics_plugin = None # Store reference if found

        self._init_ui()
        self._connect_main_window_signals()

        # Attempt to find the analytics plugin instance
        if hasattr(self.main_window, 'plugin_manager'):
            self.analytics_plugin = self.main_window.plugin_manager.get_plugin("spider_analytics_dashboard") # Use the *filename* stem

        # Initial population (if a project is already selected)
        self._on_project_changed()

    def _init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        # --- Top Selector ---
        selector_layout = QtWidgets.QHBoxLayout()
        selector_layout.addWidget(QtWidgets.QLabel("<b>Project:</b>"))
        self.project_label = QtWidgets.QLabel("<i>None Selected</i>")
        selector_layout.addWidget(self.project_label)
        selector_layout.addSpacing(20)
        selector_layout.addWidget(QtWidgets.QLabel("<b>Spider:</b>"))
        self.spider_combo = QtWidgets.QComboBox()
        self.spider_combo.setMinimumWidth(200)
        self.spider_combo.currentIndexChanged.connect(self._on_spider_selected)
        selector_layout.addWidget(self.spider_combo)
        selector_layout.addStretch()
        refresh_button = QtWidgets.QPushButton("Refresh Data")
        refresh_button.setIcon(QIcon.fromTheme("view-refresh"))
        refresh_button.clicked.connect(self._refresh_all_data)
        selector_layout.addWidget(refresh_button)
        main_layout.addLayout(selector_layout)

        # --- Splitter for Details ---
        splitter = QtWidgets.QSplitter(Qt.Vertical)

        # --- Top Pane: Info & Actions ---
        info_actions_widget = QtWidgets.QWidget()
        info_actions_layout = QtWidgets.QHBoxLayout(info_actions_widget)
        info_actions_layout.setContentsMargins(0,0,0,0)

        # Info Group
        info_group = QtWidgets.QGroupBox("Spider Info")
        info_layout = QtWidgets.QFormLayout(info_group)
        self.spider_file_label = QtWidgets.QLabel("<i>N/A</i>")
        self.spider_file_label.setWordWrap(True)
        self.schedule_info_label = QtWidgets.QLabel("<i>Not Scheduled</i>")
        self.schedule_info_label.setWordWrap(True)
        info_layout.addRow("Definition File:", self.spider_file_label)
        info_layout.addRow("Schedule Status:", self.schedule_info_label)
        info_actions_layout.addWidget(info_group, 1) # Stretch factor 1

        # Actions Group
        actions_group = QtWidgets.QGroupBox("Quick Actions")
        actions_layout = QtWidgets.QVBoxLayout(actions_group)
        self.open_code_button = QtWidgets.QPushButton("Open Code in Editor")
        self.open_code_button.setIcon(QIcon.fromTheme("document-edit"))
        self.open_code_button.clicked.connect(self._open_spider_code)
        self.run_spider_button = QtWidgets.QPushButton("Run Spider Now")
        self.run_spider_button.setIcon(QIcon.fromTheme("media-playback-start"))
        self.run_spider_button.clicked.connect(self._run_spider_now)
        self.view_schedule_button = QtWidgets.QPushButton("View/Edit Schedule")
        self.view_schedule_button.setIcon(QIcon.fromTheme("view-calendar-list"))
        self.view_schedule_button.clicked.connect(self._go_to_schedule)
        actions_layout.addWidget(self.open_code_button)
        actions_layout.addWidget(self.run_spider_button)
        actions_layout.addWidget(self.view_schedule_button)
        actions_layout.addStretch()
        info_actions_layout.addWidget(actions_group)

        splitter.addWidget(info_actions_widget)

        # --- Middle Pane: Recent Runs ---
        runs_group = QtWidgets.QGroupBox("Recent Runs & History")
        runs_layout = QtWidgets.QVBoxLayout(runs_group)
        self.runs_table = QtWidgets.QTableWidget()
        self.runs_table.setColumnCount(6)
        self.runs_table.setHorizontalHeaderLabels(["Run ID", "Started", "Finished", "Status", "Items", "Actions"])
        self.runs_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.runs_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.runs_table.horizontalHeader().setStretchLastSection(True)
        self.runs_table.verticalHeader().setVisible(False)
        runs_layout.addWidget(self.runs_table)
        splitter.addWidget(runs_group)

        # --- Bottom Pane: Analytics Summary ---
        analytics_group = QtWidgets.QGroupBox("Analytics Summary (Requires Analytics Plugin)")
        analytics_layout = QtWidgets.QVBoxLayout(analytics_group)
        self.analytics_summary_label = QtWidgets.QLabel("<i>Analytics plugin not found or no data available for this spider.</i>")
        self.analytics_summary_label.setAlignment(Qt.AlignCenter)
        self.analytics_summary_label.setWordWrap(True)
        analytics_layout.addWidget(self.analytics_summary_label)
        splitter.addWidget(analytics_group)

        main_layout.addWidget(splitter)

        # Set initial sizes for splitter (adjust as needed)
        splitter.setSizes([150, 300, 100])

        # Initial state is disabled until spider selected
        self._enable_widgets(False)

    def _connect_main_window_signals(self):
        """Connect to signals from the main window if possible."""
        # Need a way for MainWindow to signal project changes.
        # Option 1: MainWindow explicitly calls a method here (less decoupled)
        # Option 2: MainWindow emits a custom signal (better)
        # Option 3: Poll or check on tab activation (simpler for now)
        # Let's rely on manual refresh and checking on spider selection for now.
        # If MainWindow.project_list exists, we can connect to its itemClicked
        if hasattr(self.main_window, 'project_list'):
            self.main_window.project_list.itemClicked.connect(self._on_project_changed)
        else:
            logger.warning("Cannot connect to main_window.project_list signal.")


    @Slot()
    def _on_project_changed(self):
        """Update when the project selection changes in the main window."""
        logger.debug("Dashboard received project change signal.")
        if hasattr(self.main_window, 'current_project') and self.main_window.current_project:
            self.current_project_data = self.main_window.current_project
            project_name = self.current_project_data.get('name', 'Unknown')
            self.project_label.setText(f"<b>{project_name}</b>")
            self._populate_spider_combo()
        else:
            self.current_project_data = None
            self.project_label.setText("<i>None Selected</i>")
            self.spider_combo.clear()
            self._clear_all_data()
            self._enable_widgets(False)

    def _populate_spider_combo(self):
        """Fills the spider dropdown based on the current project."""
        self.spider_combo.clear()
        self.spider_combo.addItem("Select a Spider...")
        self.current_spider_name = None
        self._clear_all_data()
        self._enable_widgets(False)

        if not self.current_project_data or not hasattr(self.main_window, 'project_controller'):
            return

        try:
            project_name = self.current_project_data['name']
            spiders = self.main_window.project_controller.get_project_spiders(project_name)
            if spiders:
                self.spider_combo.addItems(sorted(spiders))
            else:
                logger.info(f"No spiders found for project {project_name}")
        except Exception as e:
            logger.error(f"Error getting spiders for project {self.current_project_data.get('name')}: {e}")

    @Slot(int)
    def _on_spider_selected(self, index):
        """Load data when a spider is selected from the dropdown."""
        if index <= 0: # Ignore "Select a Spider..."
            self.current_spider_name = None
            self._clear_all_data()
            self._enable_widgets(False)
            return

        self.current_spider_name = self.spider_combo.currentText()
        logger.info(f"Spider selected in dashboard: {self.current_spider_name}")
        self._enable_widgets(True)
        self._load_spider_data()

    @Slot()
    def _refresh_all_data(self):
         """Manually refresh all data for the selected project/spider."""
         logger.debug("Manual refresh triggered.")
         self._on_project_changed() # Repopulate spiders based on current main window state
         # Re-select the currently chosen spider to trigger data load
         current_text = self.spider_combo.currentText()
         if current_text != "Select a Spider...":
              index = self.spider_combo.findText(current_text)
              if index >= 0:
                   self.spider_combo.setCurrentIndex(index) # Will trigger _on_spider_selected
                   self._load_spider_data() # Explicitly call load data as well
              else:
                   # Spider might no longer exist, clear data
                   self._clear_all_data()
                   self._enable_widgets(False)


    def _clear_all_data(self):
         """Clears all displayed spider-specific information."""
         self.spider_file_label.setText("<i>N/A</i>")
         self.schedule_info_label.setText("<i>N/A</i>")
         self.runs_table.setRowCount(0)
         self.analytics_summary_label.setText("<i>Select a spider to see analytics.</i>")

    def _enable_widgets(self, enable):
         """Enable/disable action buttons and other controls."""
         self.open_code_button.setEnabled(enable)
         self.run_spider_button.setEnabled(enable)
         self.view_schedule_button.setEnabled(enable)
         # Add others if needed

    def _load_spider_data(self):
        """Loads and displays all data related to the selected spider."""
        if not self.current_project_data or not self.current_spider_name:
            return

        self._clear_all_data() # Clear previous data first
        logger.debug(f"Loading data for spider: {self.current_spider_name}")

        project_path = Path(self.current_project_data.get('path', ''))
        spider_name = self.current_spider_name

        # 1. Find Definition File
        spider_file = self._find_spider_file(project_path, spider_name)
        if spider_file:
            self.spider_file_label.setText(str(spider_file.relative_to(project_path)))
            self.open_code_button.setEnabled(True)
            self.open_code_button.setProperty("spider_file_path", str(spider_file)) # Store path
        else:
            self.spider_file_label.setText("<i>Could not locate file!</i>")
            self.open_code_button.setEnabled(False)

        # 2. Load Run History (Prefer Analytics, fallback to SpiderController history)
        self._load_run_history(spider_name)

        # 3. Load Schedule Info
        self._load_schedule_info(spider_name)

        # 4. Load Analytics Summary
        self._load_analytics_summary(spider_name)


    def _find_spider_file(self, project_path, spider_name):
        """Attempts to find the python file defining the spider."""
        if not project_path or not project_path.is_dir():
            return None

        # Standard structure: project_dir/project_name/spiders/spider_name.py
        # Fallback structure: project_dir/spiders/spider_name.py
        possible_paths = [
            project_path / self.current_project_data.get('name', '') / 'spiders' / f"{spider_name}.py",
            project_path / 'spiders' / f"{spider_name}.py"
        ]

        for path in possible_paths:
            if path.exists() and path.is_file():
                logger.debug(f"Found spider definition: {path}")
                return path

        # If exact match fails, search all .py files in spiders dir (slower)
        spiders_dirs = [
             project_path / self.current_project_data.get('name', '') / 'spiders',
             project_path / 'spiders'
             ]
        for sdir in spiders_dirs:
             if sdir.exists() and sdir.is_dir():
                  try:
                       for py_file in sdir.glob("*.py"):
                            # Basic check for spider name in file content
                            content = py_file.read_text(encoding='utf-8', errors='ignore')
                            if f"name = '{spider_name}'" in content or f'name = "{spider_name}"' in content:
                                 logger.debug(f"Found spider definition (via content search): {py_file}")
                                 return py_file
                  except Exception as e:
                       logger.warning(f"Error searching for spider file content in {sdir}: {e}")

        logger.warning(f"Could not find definition file for spider: {spider_name} in project {project_path}")
        return None

    def _load_run_history(self, spider_name):
        """Populates the runs table, preferring analytics data."""
        self.runs_table.setRowCount(0) # Clear table
        all_runs = []

        # Try Analytics Plugin
        if self.analytics_plugin and hasattr(self.analytics_plugin, 'analytics_data'):
            spider_runs = self.analytics_plugin.analytics_data.get(spider_name, [])
            if spider_runs:
                logger.debug(f"Loading run history from Analytics Plugin for {spider_name}")
                # Analytics data already has the desired structure
                all_runs = sorted(spider_runs, key=lambda x: x.get('timestamp', 0), reverse=True)
            else:
                logger.info(f"Analytics plugin found, but no runs recorded for spider {spider_name}")
        else:
            logger.warning("Analytics plugin not found or unavailable. Cannot display run history.")
            # Display a message in the table? Or just leave it empty.
            # Example: self.runs_table.setItem(0, 0, create_table_item("Analytics Plugin needed for history"))
            return # Stop if no analytics source

       

        if not all_runs:
            logger.info(f"No run history found for spider {spider_name}")
            return

        self.runs_table.setRowCount(len(all_runs))
        for row, run_info in enumerate(all_runs):
            run_id = run_info.get('run_id', f'unknown_{row}')
            start_time = format_timestamp(run_info.get('start_time'))
            end_time = format_timestamp(run_info.get('end_time'))
            status = run_info.get('status', 'unknown')
            items = run_info.get('item_count', 'N/A')

            self.runs_table.setItem(row, 0, create_table_item(run_id, tooltip=f"Run ID: {run_id}"))
            self.runs_table.setItem(row, 1, create_table_item(start_time))
            self.runs_table.setItem(row, 2, create_table_item(end_time))

            status_item = create_table_item(status)
            if status == 'completed':
                status_item.setForeground(QColor('darkgreen'))
            elif 'fail' in status or 'error' in status:
                status_item.setForeground(QColor('red'))
            elif status == 'running':
                 status_item.setForeground(QColor('blue'))
            self.runs_table.setItem(row, 3, status_item)

            self.runs_table.setItem(row, 4, create_table_item(items))

            # Actions Cell
            actions_widget = QtWidgets.QWidget()
            actions_layout = QtWidgets.QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(5)

            log_path = run_info.get("log_file")
            output_path = run_info.get("output_file")

            view_log_btn = QtWidgets.QPushButton("Log")
            view_log_btn.setIcon(QIcon.fromTheme("text-x-generic"))
            view_log_btn.setToolTip(f"View Log File:\n{log_path or 'N/A'}")
            view_log_btn.setEnabled(bool(log_path and Path(log_path).exists()))
            if view_log_btn.isEnabled():
                # Use lambda with default arg to capture current log_path
                view_log_btn.clicked.connect(lambda checked=False, lp=log_path: self._go_to_log(lp))
            actions_layout.addWidget(view_log_btn)

            view_output_btn = QtWidgets.QPushButton("Output")
            view_output_btn.setIcon(QIcon.fromTheme("application-json", QIcon.fromTheme("text-csv"))) # Try JSON or CSV icon
            view_output_btn.setToolTip(f"View Output File:\n{output_path or 'N/A'}")
            view_output_btn.setEnabled(bool(output_path and Path(output_path).exists()))
            if view_output_btn.isEnabled():
                view_output_btn.clicked.connect(lambda checked=False, op=output_path: self._go_to_output(op))
            actions_layout.addWidget(view_output_btn)

            actions_layout.addStretch()
            self.runs_table.setCellWidget(row, 5, actions_widget)

        self.runs_table.resizeColumnsToContents()
        self.runs_table.horizontalHeader().setStretchLastSection(True) # Re-apply stretch

    def _load_schedule_info(self, spider_name):
        """Checks if the spider is scheduled."""
        self.schedule_info_label.setText("<i>Checking...</i>")
        self.view_schedule_button.setEnabled(False) # Disable until checked

        if not hasattr(self.main_window, 'scheduler'):
            self.schedule_info_label.setText("<i>Scheduler Unavailable</i>")
            return

        try:
            jobs = self.main_window.scheduler.get_jobs()
            found = False
            for job_id, job_info in jobs.items():
                 # Check project path and spider name match
                 job_proj_path = Path(job_info.get('project_path',''))
                 current_proj_path = Path(self.current_project_data.get('path',''))
                 # Resolve paths before comparing for robustness
                 if (job_info.get('spider_name') == spider_name and
                     job_proj_path.resolve() == current_proj_path.resolve()):

                      interval = job_info.get('interval', 'N/A')
                      enabled = job_info.get('enabled', False)
                      next_run = format_timestamp(job_info.get('next_run')) if enabled else "Disabled"
                      status_color = "darkgreen" if enabled else "orange"

                      self.schedule_info_label.setText(f"<b style='color:{status_color};'>{'Enabled' if enabled else 'Disabled'}</b> | Interval: {interval} | Next: {next_run}")
                      self.view_schedule_button.setEnabled(True) # Enable button if found
                      found = True
                      break # Assume only one schedule per spider/project

            if not found:
                self.schedule_info_label.setText("<i>Not Scheduled</i>")

        except Exception as e:
            logger.error(f"Error getting schedule info for {spider_name}: {e}")
            self.schedule_info_label.setText("<i>Error loading schedule</i>")

    def _load_analytics_summary(self, spider_name):
        """Loads summary stats from the analytics plugin."""
        if not self.analytics_plugin:
            self.analytics_summary_label.setText("<i>Analytics plugin not found.</i>")
            return

        # --- Force reload from disk ---
        if hasattr(self.analytics_plugin, 'load_analytics_data'):
             logger.debug("Dashboard forcing analytics plugin to reload data.")
             self.analytics_plugin.load_analytics_data()
        else:
             logger.warning("Analytics plugin does not have 'load_analytics_data' method for refresh.")
        # --- End Force reload ---


        if not hasattr(self.analytics_plugin, 'analytics_data'):
            self.analytics_summary_label.setText("<i>Analytics plugin data attribute unavailable.</i>")
            return

        spider_runs = self.analytics_plugin.analytics_data.get(spider_name, [])
        if not spider_runs:
            self.analytics_summary_label.setText("<i>No analytics data recorded for this spider yet.</i>")
            return

        try:
             completed_runs = [r for r in spider_runs if r.get('status') == 'completed' and r.get('duration_seconds', 0) > 0]
             total_runs = len(spider_runs)
             num_completed = len(completed_runs)
             num_failed = len([r for r in spider_runs if 'fail' in r.get('status','')])
             num_items = [r.get('item_count', 0) for r in completed_runs]
             durations = [r.get('duration_seconds', 0) for r in completed_runs]
             ips = [(n / d) if d > 0 else 0 for n, d in zip(num_items, durations)]

             avg_items = sum(num_items) / num_completed if num_completed else 0
             avg_duration = sum(durations) / num_completed if num_completed else 0
             avg_ips = sum(ips) / num_completed if num_completed else 0
             max_items = max(num_items) if num_items else 0
             last_run_time = format_timestamp(spider_runs[-1].get('start_time')) if spider_runs else "N/A" # Assuming sorted

             summary = (
                 f"<b>Total Runs Recorded:</b> {total_runs}<br>"
                 f"<b>Completed Runs:</b> {num_completed} | <b>Failed Runs:</b> {num_failed}<br>"
                 f"<b>Last Run Started:</b> {last_run_time}<br>"
                 f"--- Averages (Completed Runs) ---<br>"
                 f"<b>Avg. Items:</b> {avg_items:.1f}<br>"
                 f"<b>Avg. Duration:</b> {avg_duration:.1f} seconds<br>"
                 f"<b>Avg. Items/Sec:</b> {avg_ips:.2f}<br>"
                 f"<b>Max Items in Run:</b> {max_items}"
             )
             self.analytics_summary_label.setText(summary)

        except Exception as e:
             logger.error(f"Error calculating analytics summary for {spider_name}: {e}")
             self.analytics_summary_label.setText("<i>Error calculating analytics summary.</i>")


    # --- Action Methods ---
    @Slot()
    def _open_spider_code(self):
        """Opens the spider definition file in the main editor."""
        if not hasattr(self.main_window, '_open_file'):
             logger.error("Main window missing '_open_file' method.")
             return
        file_path = self.open_code_button.property("spider_file_path")
        if file_path and Path(file_path).exists():
            self.main_window._open_file(file_path)
        else:
            QMessageBox.warning(self, "File Not Found", "Could not find the spider's definition file.")

    @Slot()
    def _run_spider_now(self):
        """Triggers a run of the selected spider via the main window's logic."""
        if not self.current_project_data or not self.current_spider_name:
             return
        if not hasattr(self.main_window, '_run_spider') or not hasattr(self.main_window, 'spider_list'):
             logger.error("Main window missing '_run_spider' method or 'spider_list'. Cannot run spider.")
             QMessageBox.critical(self, "Error", "Cannot trigger spider run from main application.")
             return

        # Need to select the spider in the main 'Spiders' tab list first
        # This is a bit of coupling, but necessary to use the existing run logic
        spider_list_widget = self.main_window.spider_list
        found_item = None
        for i in range(spider_list_widget.rowCount()):
             item = spider_list_widget.item(i, 0) # Assuming name is in column 0
             if item and item.text() == self.current_spider_name:
                  spider_list_widget.setCurrentItem(item)
                  # Also update main_window's current_spider property directly
                  self.main_window.current_spider = self.current_spider_name
                  self.main_window.run_action.setEnabled(True) # Ensure run action is enabled
                  found_item = item
                  break

        if found_item:
             logger.info(f"Triggering run for {self.current_spider_name} via main window.")
             self.main_window._run_spider() # Call the main window's run method
        else:
             logger.warning(f"Could not find {self.current_spider_name} in main spider list to trigger run.")
             QMessageBox.warning(self, "Spider Not Found", "Could not find the spider in the main 'Spiders' list.")

    @Slot()
    def _go_to_schedule(self):
        """Switches to the main Schedule tab."""
        if hasattr(self.main_window, 'tab_widget') and hasattr(self.main_window, 'schedule_tab'):
            self.main_window.tab_widget.setCurrentWidget(self.main_window.schedule_tab)
            # Optional: highlight the relevant job in the schedule table (more complex)
        else:
            logger.warning("Could not find Schedule tab in main window.")

    @Slot(str)
    def _go_to_log(self, log_path_str):
        logger.info(f"Dashboard: _go_to_log triggered for path: '{log_path_str}'")
        if not log_path_str:
            logger.warning("Dashboard: _go_to_log called with empty path.")
            return

        # --- Check Main Window Components ---
        if not hasattr(self.main_window, 'log_viewer'):
            logger.error("Dashboard: Main window missing 'log_viewer'. Cannot display log.")
            QMessageBox.critical(self, "Error", "Log viewer component not found in main application.")
            return
        if not hasattr(self.main_window, 'logs_tab'):
            logger.error("Dashboard: Main window missing 'logs_tab'. Cannot switch tab.")
            # Might still be able to show content, but won't switch tab
            # return # Optional: stop if tab switching is essential
        if not hasattr(self.main_window, 'tab_widget'):
            logger.error("Dashboard: Main window missing 'tab_widget'. Cannot switch tab.")
            # Might still be able to show content, but won't switch tab
            # return # Optional: stop if tab switching is essential

        log_path = Path(log_path_str)
        logger.debug(f"Dashboard: Checking existence of log path: {log_path}")

        if log_path.exists() and log_path.is_file():
             try:
                  logger.debug(f"Dashboard: Reading log content from {log_path}")
                  # Read with size limit for potentially huge logs
                  MAX_LOG_SIZE = 5 * 1024 * 1024 # 5 MB limit
                  file_size = log_path.stat().st_size
                  if file_size > MAX_LOG_SIZE:
                       log_content = f"--- Log file truncated (>{MAX_LOG_SIZE // 1024 // 1024}MB) ---\n"
                       with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                           # Seek near the end, but read back to find a newline
                           seek_pos = max(0, file_size - MAX_LOG_SIZE)
                           f.seek(seek_pos)
                           f.readline() # Read potential partial line
                           log_content += f.read() # Read the rest
                       QMessageBox.warning(self, "Log Too Large", f"Log file is very large ({file_size // 1024 // 1024}MB).\nShowing the last part only.")
                  else:
                       log_content = log_path.read_text(encoding='utf-8', errors='ignore')

                  logger.debug(f"Dashboard: Setting log viewer text ({len(log_content)} chars).")
                  self.main_window.log_viewer.setPlainText(log_content) # Set content

                  if hasattr(self.main_window, 'tab_widget') and hasattr(self.main_window, 'logs_tab'):
                      logger.debug("Dashboard: Switching to logs tab.")
                      self.main_window.tab_widget.setCurrentWidget(self.main_window.logs_tab) # Switch tab
                  else:
                       logger.warning("Dashboard: Could not switch to logs tab (missing component).")

                  if hasattr(self.main_window, 'statusBar'):
                      self.main_window.statusBar().showMessage(f"Loaded log: {log_path.name}", 5000)

             except Exception as e:
                  logger.error(f"Dashboard: Failed to read or display log file {log_path}: {e}", exc_info=True)
                  QMessageBox.warning(self, "Log Read Error", f"Could not read log file:\n{e}")
        else:
             logger.warning(f"Dashboard: Log file does not exist or is not a file: {log_path}")
             QMessageBox.warning(self, "Log Not Found", f"Log file does not exist:\n{log_path}")
             # Optionally, refresh the history table here as the state is inconsistent
             # self._load_run_history(self.current_spider_name)

    @Slot(str)
    def _go_to_output(self, output_path_str):
        logger.info(f"Dashboard: _go_to_output triggered for path: '{output_path_str}'")
        if not output_path_str:
            logger.warning("Dashboard: _go_to_output called with empty path.")
            return

        # --- Check Main Window Components ---
        required_attrs = ['output_files_list', '_on_output_file_selected', 'tab_widget', 'output_tab']
        missing_attrs = [attr for attr in required_attrs if not hasattr(self.main_window, attr)]
        if missing_attrs:
            logger.error(f"Dashboard: Main window missing required output components: {', '.join(missing_attrs)}. Cannot display output.")
            QMessageBox.critical(self, "Error", f"Required output components missing in main application: {', '.join(missing_attrs)}")
            return

        output_path = Path(output_path_str)
        logger.debug(f"Dashboard: Checking existence of output path: {output_path}")

        if not output_path.exists() or not output_path.is_file():
            logger.warning(f"Dashboard: Output file does not exist or is not a file: {output_path}")
            QMessageBox.warning(self, "Output Not Found", f"Output file does not exist:\n{output_path}")
             # Optionally, refresh the history table here as the state is inconsistent
             # self._load_run_history(self.current_spider_name)
            return

        # --- Find the corresponding item in the main output list ---
        output_list_widget = self.main_window.output_files_list
        target_item = None
        logger.debug(f"Dashboard: Searching for output path '{str(output_path)}' in main output list ({output_list_widget.count()} items).")

        for i in range(output_list_widget.count()):
            item = output_list_widget.item(i)
            item_path_str = item.data(QtCore.Qt.UserRole) # Path stored here
            if item_path_str:
                # Compare resolved Path objects for robustness
                try:
                    item_path = Path(item_path_str).resolve()
                    target_path_resolved = output_path.resolve()
                    # logger.debug(f"  Item {i}: Comparing ItemPath='{item_path}' vs TargetPath='{target_path_resolved}'") # Verbose
                    if item_path == target_path_resolved:
                        target_item = item
                        logger.info(f"Dashboard: Found matching item at index {i} for '{output_path.name}'.")
                        break
                except Exception as e:
                    logger.warning(f"Dashboard: Error resolving/comparing path for list item {i} ('{item_path_str}'): {e}")
            else:
                logger.warning(f"Dashboard: List item {i} has no path data.")


        if target_item:
            logger.info("Dashboard: Selecting item in main list and switching to output tab.")
            # Select the item in the list
            output_list_widget.setCurrentItem(target_item)
            # Call the handler function directly (simulates click) - Ensure this method exists and works!
            if callable(getattr(self.main_window, '_on_output_file_selected', None)):
                 try:
                     self.main_window._on_output_file_selected(target_item)
                 except Exception as e:
                      logger.error(f"Dashboard: Error calling main_window._on_output_file_selected: {e}", exc_info=True)
                      QMessageBox.critical(self, "Error", f"Failed to load output data via main window:\n{e}")
                      return # Stop if loading failed
            else:
                 logger.error("Dashboard: main_window._on_output_file_selected method not found or not callable.")
                 QMessageBox.critical(self, "Error", "Main application cannot handle output file selection.")
                 return # Stop if handler missing

            # Switch to the output tab
            self.main_window.tab_widget.setCurrentWidget(self.main_window.output_tab)
            if hasattr(self.main_window, 'statusBar'):
                self.main_window.statusBar().showMessage(f"Showing output: {output_path.name}", 5000)
        else:
            logger.warning(f"Dashboard: Could not find output file '{output_path.name}' in main output list.")
            # Fallback: Try opening in editor
            if hasattr(self.main_window, '_open_file'):
                 logger.info("Dashboard: Attempting to open output file in editor as fallback.")
                 opened = self.main_window._open_file(str(output_path))
                 if not opened:
                      QMessageBox.warning(self, "Output Load Failed", f"Could not find '{output_path.name}' in the output list and failed to open it in the editor.")
            else:
                logger.error("Dashboard: Fallback failed - main window missing '_open_file' method.")
                QMessageBox.warning(self, "Output Load Failed", f"Could not find '{output_path.name}' in the output list and cannot open in editor.")


# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Plugin to add a Spider Dashboard tab for cross-referencing spider info.
    """
    def __init__(self):
        super().__init__()
        self.name = "Spider Dashboard"
        self.description = "Central dashboard to view spider code, runs, output, analytics, and schedules."
        self.version = "1.0.0"
        self.main_window = None
        self.dashboard_tab = None

    def initialize_ui(self, main_window):
        """Create the Dashboard tab and add it to the main window."""
        self.main_window = main_window

        if hasattr(main_window, 'tab_widget'):
            try:
                self.dashboard_tab = SpiderDashboardWidget(main_window)
                icon = QIcon.fromTheme("utilities-system-monitor", QIcon()) # System monitor icon
                main_window.tab_widget.addTab(self.dashboard_tab, icon, "Spider Dashboard")
                logger.info("Spider Dashboard plugin initialized UI.")
            except Exception as e:
                logger.exception("Failed to initialize Spider Dashboard UI:")
                QMessageBox.critical(main_window, "Plugin Error", f"Failed to initialize Spider Dashboard:\n{e}")

        else:
            logger.error("Could not find main window's tab_widget to add Dashboard tab.")

    # This plugin primarily reads data, so on_spider_started/finished might not be
    # strictly needed unless we want real-time updates *within* the dashboard itself.
    # The refresh button and selecting the spider handle data loading for now.

    def on_app_exit(self):
        """Placeholder for cleanup if needed."""
        logger.info("Spider Dashboard plugin exiting.")