"""
Spider Analytics Dashboard Plugin for Scrapy Spider Manager.
Provides analytics, graphs, and insights for spider runs over time.
"""
import logging
import os
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
from collections import defaultdict

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QAction, QIcon, QPalette, QColor
from PySide6.QtCore import Qt, QTimer

from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Analytics DB Path ---
BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = BASE_DIR / "data" / "spider_analytics.json"

class SpiderPerformanceWidget(QtWidgets.QWidget):
    """Widget for displaying spider performance metrics."""
    def __init__(self, dashboard, parent=None):
        super().__init__(parent)
        self.dashboard = dashboard  # Store direct reference
        self.setMinimumHeight(300)
        self.performance_data = {}
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Create chart area
        self.figure = Figure(figsize=(5, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(250)
        layout.addWidget(self.canvas)
        
        # Controls area
        controls_layout = QtWidgets.QHBoxLayout()
        
        # Spider selection
        self.spider_combo = QtWidgets.QComboBox()
        self.spider_combo.currentIndexChanged.connect(self.update_chart)
        controls_layout.addWidget(QtWidgets.QLabel("Spider:"))
        controls_layout.addWidget(self.spider_combo)
        
        # Metric selection
        self.metric_combo = QtWidgets.QComboBox()
        self.metric_combo.addItems(["Items Scraped", "Run Duration", "Items Per Second"])
        self.metric_combo.currentIndexChanged.connect(self.update_chart)
        controls_layout.addWidget(QtWidgets.QLabel("Metric:"))
        controls_layout.addWidget(self.metric_combo)
        
        # Time range
        self.range_combo = QtWidgets.QComboBox()
        self.range_combo.addItems(["Last 5 Runs", "Last 10 Runs", "Last 30 Days", "All Time"])
        self.range_combo.currentIndexChanged.connect(self.update_chart)
        controls_layout.addWidget(QtWidgets.QLabel("Range:"))
        controls_layout.addWidget(self.range_combo)
        
        # Refresh button
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        controls_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(controls_layout)
        
        # Stats area
        self.stats_label = QtWidgets.QLabel("No data available")
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.stats_label)
        
    def set_data(self, performance_data):
        """Set the performance data and update the UI."""
        self.performance_data = performance_data
        
        # Update spider dropdown
        self.spider_combo.clear()
        spiders = sorted(self.performance_data.keys())
        if spiders:
            self.spider_combo.addItems(spiders)
            
        # Update chart
        self.update_chart()
        
    def refresh_data(self):
        """Signal that data should be refreshed."""
        self.dashboard.refresh_analytics_data()
        # Find the dashboard through the plugin instead of widget hierarchy
        if hasattr(self.parent(), 'plugin') and self.parent().plugin:
            self.parent().plugin.dashboard.refresh_analytics_data()
        else:
            # Alternative method to find the dashboard
            dashboard = self.parent()
            if hasattr(dashboard, 'refresh_analytics_data'):
                dashboard.refresh_analytics_data()
        
    def update_chart(self):
        """Update the chart based on current selections."""
        # Clear the figure
        self.figure.clear()
        
        # Get selected values
        spider = self.spider_combo.currentText()
        metric = self.metric_combo.currentText()
        time_range = self.range_combo.currentText()
        
        if not spider or spider not in self.performance_data or not self.performance_data[spider]:
            # No data available
            self.stats_label.setText("No data available")
            self.canvas.draw()
            return
        
        # Filter data based on time range
        runs = self.performance_data[spider]
        filtered_runs = self._filter_by_time_range(runs, time_range)
        
        if not filtered_runs:
            self.stats_label.setText(f"No data available for selected time range")
            self.canvas.draw()
            return
        
        # Extract metric values
        dates = []
        values = []
        
        for run in filtered_runs:
            dates.append(run.get('date', 'Unknown'))
            
            if metric == "Items Scraped":
                values.append(run.get('item_count', 0))
            elif metric == "Run Duration":
                values.append(run.get('duration_seconds', 0) / 60)  # Convert to minutes
            elif metric == "Items Per Second":
                duration = run.get('duration_seconds', 0)
                items = run.get('item_count', 0)
                ips = items / duration if duration > 0 else 0
                values.append(ips)
        
        # Create chart
        ax = self.figure.add_subplot(111)
        
        # Bar chart with date labels
        bars = ax.bar(range(len(values)), values, color='skyblue')
        
        # Set x-axis labels
        ax.set_xticks(range(len(dates)))
        if len(dates) > 6:
            # If many dates, only show some labels to avoid overcrowding
            step = max(1, len(dates) // 6)
            visible_indices = list(range(0, len(dates), step))
            if len(dates)-1 not in visible_indices:
                visible_indices.append(len(dates)-1)  # Always show the last date
            
            ax.set_xticks(visible_indices)
            ax.set_xticklabels([dates[i] for i in visible_indices], rotation=45, ha="right")
        else:
            ax.set_xticklabels(dates, rotation=45, ha="right")
        
        # Set chart title and labels
        ax.set_title(f"{metric} for {spider}")
        
        if metric == "Items Scraped":
            ax.set_ylabel("Number of Items")
            y_label = "items"
        elif metric == "Run Duration":
            ax.set_ylabel("Duration (minutes)")
            y_label = "minutes"
        elif metric == "Items Per Second":
            ax.set_ylabel("Items Per Second")
            y_label = "items/sec"
        
        # Add value labels on top of bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.01 * max(values),
                    f"{height:.1f}",
                    ha='center', va='bottom', rotation=0)
        
        # Adjust layout
        self.figure.tight_layout()
        
        # Display statistics
        avg_value = sum(values) / len(values)
        max_value = max(values)
        min_value = min(values)
        
        stats_text = (f"Average: {avg_value:.2f} {y_label} | "
                     f"Max: {max_value:.2f} {y_label} | "
                     f"Min: {min_value:.2f} {y_label} | "
                     f"Runs: {len(filtered_runs)}")
        
        self.stats_label.setText(stats_text)
        
        # Draw canvas
        self.canvas.draw()
    
    def _filter_by_time_range(self, runs, time_range):
        """Filter runs by the selected time range."""
        # Sort runs by date, most recent first
        sorted_runs = sorted(runs, key=lambda x: x.get('timestamp', 0), reverse=True)
        
        if time_range == "Last 5 Runs":
            return sorted_runs[:5]
        elif time_range == "Last 10 Runs":
            return sorted_runs[:10]
        elif time_range == "Last 30 Days":
            cutoff = datetime.now() - timedelta(days=30)
            cutoff_timestamp = cutoff.timestamp()
            return [run for run in sorted_runs if run.get('timestamp', 0) >= cutoff_timestamp]
        else:  # All Time
            return sorted_runs


class SpiderRunSummaryWidget(QtWidgets.QWidget):
    """Widget showing summary of recent spider runs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        
    def _init_ui(self):
        """Initialize the UI components."""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Summary table
        self.summary_table = QtWidgets.QTableWidget()
        self.summary_table.setColumnCount(7)
        self.summary_table.setHorizontalHeaderLabels([
            "Spider", "Last Run", "Status", "Items", "Duration", "Avg Items/sec", "Output Format"
        ])
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.summary_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        
        layout.addWidget(self.summary_table)
        
    def set_data(self, performance_data):
        """Update the summary table with the latest run for each spider."""
        # Clear table
        self.summary_table.setRowCount(0)
        
        row = 0
        for spider, runs in performance_data.items():
            if not runs:
                continue
                
            # Get most recent run
            latest_run = max(runs, key=lambda x: x.get('timestamp', 0))
            
            # Add row
            self.summary_table.insertRow(row)
            
            # Spider name
            self.summary_table.setItem(row, 0, QtWidgets.QTableWidgetItem(spider))
            
            # Last run date
            self.summary_table.setItem(row, 1, QtWidgets.QTableWidgetItem(latest_run.get('date', 'Unknown')))
            
            # Status
            status_item = QtWidgets.QTableWidgetItem(latest_run.get('status', 'Unknown'))
            if latest_run.get('status') == 'completed':
                status_item.setForeground(QColor('green'))
            elif latest_run.get('status') in ['failed', 'error']:
                status_item.setForeground(QColor('red'))
            self.summary_table.setItem(row, 2, status_item)
            
            # Items count
            self.summary_table.setItem(row, 3, QtWidgets.QTableWidgetItem(str(latest_run.get('item_count', 0))))
            
            # Duration
            duration_secs = latest_run.get('duration_seconds', 0)
            if duration_secs >= 60:
                mins = duration_secs // 60
                secs = duration_secs % 60
                duration_str = f"{mins}m {secs}s"
            else:
                duration_str = f"{duration_secs}s"
            self.summary_table.setItem(row, 4, QtWidgets.QTableWidgetItem(duration_str))
            
            # Avg items per second
            ips = 0
            if duration_secs > 0:
                ips = latest_run.get('item_count', 0) / duration_secs
            self.summary_table.setItem(row, 5, QtWidgets.QTableWidgetItem(f"{ips:.2f}"))
            
            # Output format
            self.summary_table.setItem(row, 6, QtWidgets.QTableWidgetItem(latest_run.get('output_format', 'Unknown')))
            
            row += 1
            
        # Resize columns to content
        self.summary_table.resizeColumnsToContents()


class SpiderAnalyticsDashboard(QtWidgets.QWidget):
    """Main dashboard widget for spider analytics."""
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.performance_data = {}
        self._init_ui()
        
    def _init_ui(self):
        """Initialize UI components."""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Header
        header_layout = QtWidgets.QHBoxLayout()
        title_label = QtWidgets.QLabel("Spider Analytics Dashboard")
        title_label.setStyleSheet("font-weight: bold; font-size: 18px;")
        header_layout.addWidget(title_label)
        
        # Auto-refresh toggle
        self.auto_refresh = QtWidgets.QCheckBox("Auto Refresh")
        self.auto_refresh.setChecked(True)
        self.auto_refresh.stateChanged.connect(self._toggle_auto_refresh)
        header_layout.addWidget(self.auto_refresh)
        
        # Refresh interval
        header_layout.addWidget(QtWidgets.QLabel("Interval:"))
        self.refresh_interval = QtWidgets.QSpinBox()
        self.refresh_interval.setRange(5, 3600)
        self.refresh_interval.setValue(30)
        self.refresh_interval.setSuffix(" seconds")
        self.refresh_interval.valueChanged.connect(self._update_refresh_timer)
        header_layout.addWidget(self.refresh_interval)
        
        # Stretch to push refresh button to the right
        header_layout.addStretch()
        
        # Manual refresh button
        refresh_btn = QtWidgets.QPushButton("Refresh Now")
        refresh_btn.clicked.connect(self.refresh_analytics_data)
        header_layout.addWidget(refresh_btn)
        
        layout.addLayout(header_layout)
        
        # Create tabbed widget for different views
        self.tabs = QtWidgets.QTabWidget()
        
        # Performance tab
        self.performance_widget = SpiderPerformanceWidget(self)  # Pass self (dashboard) as first arg
        self.tabs.addTab(self.performance_widget, "Performance Trends")
        
        # Summary tab
        self.summary_widget = SpiderRunSummaryWidget(self)
        self.tabs.addTab(self.summary_widget, "Spiders Summary")
        
        layout.addWidget(self.tabs)
        
        # Status bar
        self.status_label = QtWidgets.QLabel("Ready")
        layout.addWidget(self.status_label)
        
        # Create refresh timer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_analytics_data)
        self._update_refresh_timer()
        
    def refresh_analytics_data(self):
        """Refresh analytics data from log files."""
        self.status_label.setText("Refreshing data...")
        
        try:
            # Request the plugin to gather data
            self.plugin.gather_analytics_data()
            
            # Get the data
            self.performance_data = self.plugin.analytics_data
            
            # Update widgets
            self.performance_widget.set_data(self.performance_data)
            self.summary_widget.set_data(self.performance_data)
            
            # Update status
            total_runs = sum(len(runs) for runs in self.performance_data.values())
            self.status_label.setText(f"Data refreshed at {datetime.now().strftime('%H:%M:%S')}. "
                                    f"{len(self.performance_data)} spiders, {total_runs} total runs.")
                                    
        except Exception as e:
            logger.exception(f"Error refreshing analytics data: {e}")
            self.status_label.setText(f"Error refreshing data: {str(e)}")
            
    def _toggle_auto_refresh(self, state):
        """Toggle automatic refresh timer."""
        if state == Qt.Checked:
            self.refresh_timer.start()
            self.refresh_interval.setEnabled(True)
        else:
            self.refresh_timer.stop()
            self.refresh_interval.setEnabled(False)
            
    def _update_refresh_timer(self):
        """Update the refresh timer interval."""
        # Convert to milliseconds
        interval_ms = self.refresh_interval.value() * 1000
        self.refresh_timer.setInterval(interval_ms)
        
        # Restart timer if it's active
        if self.auto_refresh.isChecked():
            self.refresh_timer.start()
            

class Plugin(PluginBase):
    """
    Spider Analytics Dashboard Plugin.
    Tracks and visualizes spider performance metrics.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "Spider Analytics"
        self.description = "Tracks and visualizes spider performance metrics"
        self.version = "1.0.0"
        self.analytics_data = {}
        self.dashboard = None
        self.db_file = DEFAULT_DB_PATH
        
    def initialize(self, main_window, config=None):
        """Initialize the plugin with the main window reference."""
        super().initialize(main_window, config)
        
        # Load existing analytics data
        self.load_analytics_data()
        
    def initialize_ui(self, main_window):
        """Initialize the UI components."""
        self.main_window = main_window
        
        # Add dashboard tab
        if hasattr(main_window, 'tab_widget'):
            self.dashboard = SpiderAnalyticsDashboard(self)
            main_window.tab_widget.addTab(self.dashboard, "Analytics")
            
            # Queue refresh of data for when the tab is shown
            QTimer.singleShot(1000, self.dashboard.refresh_analytics_data)
            
        # Add menu items
        menubar = main_window.menuBar()
        tools_menu = None
        
        # Find or create Tools menu
        for action in menubar.actions():
            menu = action.menu()
            if menu and action.text().lower().startswith("&tools"):
                tools_menu = menu
                break
        
        if not tools_menu:
            tools_menu = menubar.addMenu("&Tools")
        
        # Add Analytics action
        analytics_action = QAction("Spider Analytics", main_window)
        analytics_action.triggered.connect(self.show_analytics)
        tools_menu.addAction(analytics_action)
        
        logger.info("Spider Analytics Dashboard plugin initialized.")
        
    def show_analytics(self):
        """Show the analytics dashboard tab."""
        if self.dashboard and hasattr(self.main_window, 'tab_widget') and \
           self.main_window.tab_widget.currentWidget() == self.dashboard:
            # Use invokeMethod to ensure UI update happens on the main thread
             QtCore.QMetaObject.invokeMethod(
                self.dashboard, "refresh_analytics_data", Qt.ConnectionType.QueuedConnection
            )
            
    def on_spider_started(self, spider_info):
        """Record when a spider starts running."""
        run_id = spider_info.get('run_id')
        spider_name = spider_info.get('spider_name', 'unknown')
        logger.info(f"[Analytics] on_spider_started called for: run_id={run_id}, spider={spider_name}")
        if not run_id:
            logger.warning("[Analytics] No run_id in spider_info for on_spider_started.")
            return

        # Initialize data structure if needed
        if spider_name not in self.analytics_data:
            self.analytics_data[spider_name] = []

        # Check if run_id already exists (maybe from a previous incomplete run)
        existing_run = None
        for run in self.analytics_data[spider_name]:
            if run.get('run_id') == run_id:
                existing_run = run
                break

        # Prepare start info - include paths here if available, though unlikely
        start_info = {
            'run_id': run_id,
            'start_time': datetime.now().isoformat(),
            'timestamp': time.time(),
            'status': 'running',
            'spider_name': spider_name,
            'project_path': spider_info.get('project_path'), # Store project path
            'args': spider_info.get('args', {}),          # Store args
            'output_format': spider_info.get('output_format', 'unknown'),
            'log_file': spider_info.get('log_file'),      # Store log path if known at start
            'output_file': spider_info.get('output_file') # Store output path if known at start
        }
        logger.debug(f"[Analytics] Recording/Updating start info: {start_info}")

        if existing_run:
             # Update existing entry cautiously, prioritizing newer start time if needed
             existing_run.update(start_info)
             logger.debug(f"[Analytics] Updated existing record for run_id {run_id}.")
        else:
            # Add new entry
            self.analytics_data[spider_name].append(start_info)
            logger.debug(f"[Analytics] Appended new record for run_id {run_id}.")

        # Save analytics data
        self.save_analytics_data()
            
    def on_spider_finished(self, spider_info, status, item_count):
        """Record when a spider finishes running."""
        run_id = spider_info.get('run_id')
        spider_name = spider_info.get('spider_name', 'unknown')
        log_path = spider_info.get('log_file') # Get path from input
        output_path = spider_info.get('output_file') # Get path from input

        logger.info(f"[Analytics] on_spider_finished called for: run_id={run_id}, spider={spider_name}, status={status}, items={item_count}")
        logger.info(f"[Analytics] Received log_file: {log_path}")
        logger.info(f"[Analytics] Received output_file: {output_path}")

        if not run_id:
            logger.warning("[Analytics] No run_id in spider_info for on_spider_finished.")
            return

        # Initialize data structure if needed (should exist from on_spider_started)
        if spider_name not in self.analytics_data:
            logger.warning(f"[Analytics] Received finish for {spider_name} but no start record exists. Creating placeholder.")
            self.analytics_data[spider_name] = []
            # Create a basic placeholder if no start record found
            placeholder_start = {
                 'run_id': run_id,
                 'spider_name': spider_name,
                 'project_path': spider_info.get('project_path'),
                 'args': spider_info.get('args', {}),
                 'output_format': spider_info.get('output_format', 'unknown'),
                 'log_file': log_path, # Still record paths
                 'output_file': output_path,
                 'start_time': None, # Mark as unknown start
                 'timestamp': time.time() - 1, # Estimate start slightly before end
            }
            self.analytics_data[spider_name].append(placeholder_start)


        end_time = datetime.now()
        end_timestamp = time.time()
        duration_seconds = 0

        # Find the existing run record to calculate duration accurately
        target_run_index = -1
        for i, run in enumerate(self.analytics_data[spider_name]):
            if run.get('run_id') == run_id:
                target_run_index = i
                start_timestamp = run.get('timestamp')
                if start_timestamp:
                    duration_seconds = end_timestamp - start_timestamp
                else:
                     logger.warning(f"[Analytics] No start timestamp found for run {run_id} to calculate duration.")
                break
        else:
            logger.error(f"[Analytics] Could not find existing record for run_id {run_id} to update finish details.")
            # If we didn't find it, we might have just added a placeholder above
            target_run_index = len(self.analytics_data[spider_name]) - 1 # Assume it's the last one


        # Prepare completion info, **including the paths from input spider_info**
        completion_info = {
            'end_time': end_time.isoformat(),
            'status': status,
            'item_count': item_count,
            'duration_seconds': duration_seconds,
            'date': end_time.strftime('%Y-%m-%d %H:%M'), # Use end time for the simple date string
            'log_file': log_path, # *** ADD THIS ***
            'output_file': output_path, # *** ADD THIS ***
            # Optional: Update other fields if they might have changed somehow
            # 'project_path': spider_info.get('project_path'),
            # 'args': spider_info.get('args', {}),
            # 'output_format': spider_info.get('output_format', 'unknown'),
        }
        logger.debug(f"[Analytics] Recording completion info (including paths): {completion_info}")

        # Update the correct record
        if target_run_index != -1:
            self.analytics_data[spider_name][target_run_index].update(completion_info)
        else:
             logger.error(f"[Analytics] Failed logic: Could not find or place record for run {run_id}")


        # Save analytics data
        self.save_analytics_data()
        logger.info(f"[Analytics] Saved data after spider finish for {run_id}")

        # Refresh dashboard if visible (remains the same)
        if self.dashboard and hasattr(self.main_window, 'tab_widget') and \
           self.main_window.tab_widget.currentWidget() == self.dashboard:
            # Use invokeMethod to ensure UI update happens on the main thread
             QtCore.QMetaObject.invokeMethod(
                self.dashboard, "refresh_analytics_data", Qt.ConnectionType.QueuedConnection
            )
            
    def save_analytics_data(self):
        """Save analytics data to JSON file."""
        if self.db_file is None:
            logger.error("Cannot save analytics data: db_file is None")
            return
        logger.debug(f"[Analytics] Attempting to save analytics data to {self.db_file}")    
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.analytics_data, f, indent=2)
                
            logger.debug(f"[Analytics] Successfully saved analytics data.")
        except Exception as e:
            logger.error(f"[Analytics] Error saving analytics data: {e}", exc_info=True)
            
    def load_analytics_data(self):
        """Load analytics data from JSON file."""
        if not self.db_file.exists():
            logger.info(f"Analytics database file not found, starting with empty data")
            self.analytics_data = {}
            return
            
        try:
            with open(self.db_file, 'r', encoding='utf-8') as f:
                self.analytics_data = json.load(f)
                
            logger.info(f"Loaded analytics data for {len(self.analytics_data)} spiders")
        except Exception as e:
            logger.error(f"Error loading analytics data: {e}")
            self.analytics_data = {}
            
    def gather_analytics_data(self):
        """Gather analytics data from log files and output files."""
        # This method could scan log files to find missed runs
        # For now, we'll just ensure we have proper formatting
        
        # Ensure all entries have required fields
        for spider_name, runs in self.analytics_data.items():
            for run in runs:
                # Add timestamp if missing
                if 'timestamp' not in run and 'start_time' in run:
                    try:
                        dt = datetime.fromisoformat(run['start_time'])
                        run['timestamp'] = dt.timestamp()
                    except:
                        # If can't parse, use current time
                        run['timestamp'] = time.time()
                        
                # Add date string if missing
                if 'date' not in run and 'timestamp' in run:
                    dt = datetime.fromtimestamp(run['timestamp'])
                    run['date'] = dt.strftime('%Y-%m-%d %H:%M')
                    
        # Save updated data
        self.save_analytics_data()
        
    def on_app_exit(self):
        """Save data when app exits."""
        self.save_analytics_data()
        logger.info("Spider Analytics data saved on exit")