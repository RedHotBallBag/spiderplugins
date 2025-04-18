# plugins/tutorial_classroom_plugin.py
import logging
import sys
import json
import re
import uuid # For generating unique IDs for custom videos
from pathlib import Path
import webbrowser
from urllib.parse import urlparse, parse_qs
import urllib.request
import urllib.parse
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QTextEdit

# Import necessary PySide6 components
from PySide6 import QtWidgets, QtCore, QtGui

# Check for WebEngine components carefully
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_WIDGETS_AVAILABLE = True
except ImportError:
    WEBENGINE_WIDGETS_AVAILABLE = False

try:
    from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineProfile
    WEBENGINE_CORE_AVAILABLE = True
except ImportError:
    WEBENGINE_CORE_AVAILABLE = False

from PySide6.QtGui import QAction, QIcon, QDesktopServices, QFont, QColor, QPixmap
from PySide6.QtCore import Qt, Slot, QUrl, QSize, QTimer # Added QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                               QListWidget, QListWidgetItem, QLabel, QLineEdit,
                               QPushButton, QGroupBox, QGridLayout, QTextBrowser,
                               QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
                               QSizePolicy, QProgressBar) # Added QSizePolicy

# Import Plugin Base
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Constants ---
CONFIG_FILE_CURATED = Path("config/tutorials.json")
CONFIG_FILE_USER = Path("config/user_classroom_data.json")
DEFAULT_USER_DATA = {"favorites": [], "watch_later": [], "my_videos": []}

# --- Helper: Extract YouTube ID ---
def extract_youtube_id(url):
    """Extracts YouTube video ID from various URL formats."""
    if not url: return None
    try:
        # Combined regex to handle various YouTube URL formats efficiently
        regex = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
        match = re.search(regex, url)
        if match:
            return match.group(1)
    except Exception as e:
        logger.warning(f"Could not parse YouTube URL '{url}': {e}")
    logger.warning(f"Could not extract YouTube ID from URL: {url}")
    return None # Return None if extraction fails


# --- Add/Edit Custom Video Dialog ---
class AddVideoDialog(QDialog):
    def __init__(self, video_data=None, parent=None):
        super().__init__(parent)
        self.video_data = video_data or {}
        self.setWindowTitle("Add Custom Video" if not video_data else "Edit Custom Video")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.url_input = QLineEdit(self.video_data.get("url", ""))
        self.url_input.setPlaceholderText("Enter YouTube URL (e.g., https://www.youtube.com/watch?v=...)")
        form.addRow("YouTube URL*:", self.url_input)

        self.title_input = QLineEdit(self.video_data.get("title", ""))
        self.title_input.setPlaceholderText("(Optional) Defaults to Video ID if blank")
        form.addRow("Title (Optional):", self.title_input)

        self.channel_input = QLineEdit(self.video_data.get("channel_name", ""))
        form.addRow("Channel (Optional):", self.channel_input)

        self.category_input = QLineEdit(self.video_data.get("category", "Custom"))
        form.addRow("Category (Optional):", self.category_input)

        self.desc_input = QtWidgets.QTextEdit(self.video_data.get("description", ""))
        self.desc_input.setMaximumHeight(80)
        self.desc_input.setPlaceholderText("(Optional) Brief description or notes")
        form.addRow("Description (Optional):", self.desc_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_video_data(self):
        url = self.url_input.text().strip()
        video_id = extract_youtube_id(url)

        if not video_id:
            return None # Indicate failure

        # Use existing ID or generate new one
        video_internal_id = self.video_data.get("id", f"custom_{uuid.uuid4()}")
        title = self.title_input.text().strip() or f"Video: {video_id}" # Default title

        return {
            "id": video_internal_id,
            "title": title,
            "youtube_id": video_id,
            "url": url, # Store original URL
            "channel_name": self.channel_input.text().strip() or None,
            "category": self.category_input.text().strip() or "Custom",
            "description": self.desc_input.toPlainText().strip() or None,
            "is_custom": True # Flag to identify user-added videos
        }

    def accept(self):
        if not self.url_input.text().strip():
            QMessageBox.warning(self, "Input Error", "YouTube URL is required.")
            return
        if not extract_youtube_id(self.url_input.text().strip()):
            QMessageBox.warning(self, "Input Error", "Could not extract a valid YouTube Video ID from the URL.")
            return
        super().accept()
# Add these additional imports at the top of tutorial_classroom_plugin.py
import urllib.request
import urllib.parse
from PySide6.QtCore import QThread, Signal

# Add these classes before the EnhancedTutorialClassroomWidget class 

class PlaylistImportThread(QThread):
    """Thread to handle YouTube playlist fetching without blocking UI"""
    progress_signal = Signal(int, int)  # current, total
    result_signal = Signal(list, str, str)  # list of video data, playlist title, playlist ID
    error_signal = Signal(str)  # error message
    
    def __init__(self, playlist_url, custom_name=None):
        super().__init__()
        self.playlist_url = playlist_url
        self.custom_name = custom_name
        
    def run(self):
        try:
            playlist_id = self._extract_playlist_id(self.playlist_url)
            if not playlist_id:
                raise ValueError("Could not extract playlist ID from URL")
                
            playlist_title, videos = self._extract_playlist_videos(playlist_id)
            
            # Use custom name if provided
            if self.custom_name and self.custom_name.strip():
                playlist_title = self.custom_name.strip()
                
            self.result_signal.emit(videos, playlist_title, playlist_id)
        except Exception as e:
            self.error_signal.emit(str(e))
    
    def _extract_playlist_id(self, url):
        """Extract playlist ID from YouTube URL"""
        # Check for list parameter in URL
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        # First check for 'list' parameter
        if 'list' in query_params:
            return query_params['list'][0]
        
        # If not found, check if the URL itself might be a playlist ID
        playlist_id_match = re.search(r'([A-Za-z0-9_-]{13,})', url)
        if playlist_id_match:
            return playlist_id_match.group(1)
        
        return None
    
    def _extract_playlist_videos(self, playlist_id):
        """Extract videos from YouTube playlist page"""
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
        
        # Fetch the playlist page
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        req = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(req) as response:
                html = response.read().decode('utf-8')
        except Exception as e:
            raise Exception(f"Failed to fetch playlist: {str(e)}")
        
        # Extract video information from the page
        videos = []
        playlist_title = f"Playlist: {playlist_id}"  # Default title
        
        # Pattern to find initial data in the page
        initial_data_match = re.search(r'var\s+ytInitialData\s*=\s*({.+?});</script>', html)
        if not initial_data_match:
            raise Exception("Could not find playlist data in the page")
        
        try:
            # Extract and parse the JSON data
            initial_data_str = initial_data_match.group(1)
            initial_data = json.loads(initial_data_str)
            
            # Try to extract playlist title
            try:
                header = initial_data.get('header', {}).get('playlistHeaderRenderer', {})
                if header:
                    playlist_title = self._extract_text(header.get('title', {})) or playlist_title
            except Exception:
                pass  # If title extraction fails, use the default
            
            # Navigate through the JSON structure to find playlist videos
            contents = initial_data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [{}])[0].get('tabRenderer', {}).get('content', {})
            playlist_contents = contents.get('sectionListRenderer', {}).get('contents', [{}])[0].get('itemSectionRenderer', {}).get('contents', [{}])[0]
            playlist_renderer = playlist_contents.get('playlistVideoListRenderer', {})
            
            video_items = playlist_renderer.get('contents', [])
            # Filter out non-video items (sometimes there are continuation items)
            video_items = [item for item in video_items if 'playlistVideoRenderer' in item]
            
            total_videos = len(video_items)
            if total_videos == 0:
                raise Exception("No videos found in playlist")
                
            # Emit initial progress
            self.progress_signal.emit(0, total_videos)
            
            for i, item in enumerate(video_items):
                video_renderer = item.get('playlistVideoRenderer', {})
                if not video_renderer:
                    continue
                
                video_id = video_renderer.get('videoId')
                if not video_id:
                    continue
                
                # Extract basic info
                title = self._extract_text(video_renderer.get('title', {}))
                channel = self._extract_text(video_renderer.get('shortBylineText', {}))
                length_text = self._extract_text(video_renderer.get('lengthText', {}))
                
                # Set position within playlist (important for ordering)
                position = i + 1
                
                # Create video entry
                video_data = {
                    "id": f"playlist_{playlist_id}_{video_id}",  # Create a unique ID
                    "title": title or f"Video: {video_id}",
                    "youtube_id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}&list={playlist_id}",
                    "channel_name": channel or "Unknown Channel",
                    "category": f"Playlist: {playlist_title}",  # Use the playlist title in category
                    "playlist": {  # Add playlist metadata
                        "id": playlist_id,
                        "title": playlist_title,
                        "position": position  # Store position for ordering
                    },
                    "description": f"Imported from YouTube Playlist: {playlist_title}\nVideo #{position} in playlist",
                    "duration_approx": length_text or "Unknown",
                    "is_custom": True
                }
                
                videos.append(video_data)
                
                # Emit progress update (important for progress bar)
                self.progress_signal.emit(i+1, total_videos)
                
                # Sleep briefly to prevent being rate-limited and to give UI time to update
                self.msleep(50)
        
        except json.JSONDecodeError:
            raise Exception("Failed to parse playlist data")
        except Exception as e:
            raise Exception(f"Error extracting playlist data: {str(e)}")
        
        if not videos:
            raise Exception("No videos found in playlist")
            
        return playlist_title, videos
    
    def _extract_text(self, text_object):
        """Extract text from YouTube's nested text objects"""
        if not text_object:
            return None
            
        # Handle simple string
        if isinstance(text_object, str):
            return text_object
            
        # Handle runs format
        if 'runs' in text_object:
            return ''.join(run.get('text', '') for run in text_object.get('runs', []))
            
        # Handle simple text
        if 'simpleText' in text_object:
            return text_object.get('simpleText', '')
            
        return None
    
class ImportPlaylistDialog(QDialog):
    """Dialog for importing YouTube playlist"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import YouTube Playlist")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.imported_videos = []
        self.playlist_title = ""
        self.playlist_id = ""
        
        # Initialize UI
        self._init_ui()
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # URL Input
        url_layout = QHBoxLayout()
        url_label = QLabel("YouTube Playlist URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/playlist?list=...")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)
        
        # Custom Name Input
        name_layout = QHBoxLayout()
        name_label = QLabel("Custom Playlist Name (Optional):")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Leave blank to use YouTube's playlist name")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # Import button
        self.import_button = QPushButton("Import Playlist")
        self.import_button.clicked.connect(self._import_playlist)
        layout.addWidget(self.import_button)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status and results area
        self.status_label = QLabel("Enter a YouTube playlist URL to import videos")
        layout.addWidget(self.status_label)
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText("Imported videos will appear here...")
        layout.addWidget(self.results_text)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.button_box)
        
    def _import_playlist(self):
        """Start importing the playlist"""
        playlist_url = self.url_input.text().strip()
        if not playlist_url:
            QMessageBox.warning(self, "Input Error", "Please enter a YouTube playlist URL")
            return
            
        # Clear previous results
        self.results_text.clear()
        self.imported_videos = []
        self.playlist_title = ""
        self.playlist_id = ""
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        
        # Set up UI for import process
        self.status_label.setText("Importing playlist...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.import_button.setEnabled(False)
        
        # Get custom name if provided
        custom_name = self.name_input.text().strip()
        
        # Start the import thread
        self.import_thread = PlaylistImportThread(playlist_url, custom_name)
        self.import_thread.progress_signal.connect(self._update_progress)
        self.import_thread.result_signal.connect(self._handle_import_results)
        self.import_thread.error_signal.connect(self._handle_import_error)
        self.import_thread.start()
        
    def _update_progress(self, current, total):
        """Update the progress bar"""
        if total > 0:
            percent = int(current / total * 100)
            self.progress_bar.setValue(percent)
            self.status_label.setText(f"Importing videos... ({current}/{total})")
        
    def _handle_import_results(self, videos, playlist_title, playlist_id):
        """Handle successful playlist import"""
        self.imported_videos = videos
        self.playlist_title = playlist_title
        self.playlist_id = playlist_id
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Successfully imported {len(videos)} videos from '{playlist_title}'!")
        
        # Show the imported videos in the results area
        result_text = f"Imported {len(videos)} videos from playlist '{playlist_title}':\n\n"
        for i, video in enumerate(videos, 1):
            result_text += f"{i}. {video['title']} ({video['duration_approx']})\n"
            result_text += f"   Channel: {video['channel_name']}\n"
            
        self.results_text.setText(result_text)
        
        # Enable OK button to add videos
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self.import_button.setEnabled(True)
        
    def _handle_import_error(self, error_message):
        """Handle import error"""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"Error: {error_message}")
        self.import_button.setEnabled(True)
        QMessageBox.critical(self, "Import Error", f"Failed to import playlist:\n{error_message}")
        
    def get_imported_videos(self):
        """Return the list of imported videos"""
        return self.imported_videos
        
    def get_playlist_info(self):
        """Return the playlist title and ID"""
        return {
            "title": self.playlist_title,
            "id": self.playlist_id
        }

# --- Main Enhanced Tutorial Widget ---
class EnhancedTutorialClassroomWidget(QWidget):
    """Enhanced main widget for the Tutorial Classroom tab with 3 panes."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.curated_tutorials = []
        self.user_data = DEFAULT_USER_DATA.copy() # Holds favs, watch_later, my_videos
        self.combined_videos = {} # {video_id: video_data} for easy lookup
        self.current_nav_selection = "All Curated" # Default to initial nav text
        self.current_video_data = None
        self.nav_data_map = {} # To map nav list text back to type/category

        self._init_ui()
        self._load_all_data() # This now also calls initial population and selection

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left Pane: Navigation ---
        nav_widget = QWidget()
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0,0,0,0)
        nav_widget.setMinimumWidth(180)
        nav_widget.setMaximumWidth(280)

        nav_title = QLabel("Navigation")
        nav_title.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
        nav_layout.addWidget(nav_title)

        self.nav_list = QListWidget()
        self.nav_list.currentItemChanged.connect(self._on_nav_selected)
        nav_layout.addWidget(self.nav_list)

        main_splitter.addWidget(nav_widget)

        # --- Middle Pane: Video List & Search ---
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(5,0,0,0) # Add small left margin
        middle_widget.setMinimumWidth(250)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search videos...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_video_list)
        search_layout.addWidget(self.search_input)

        self.add_video_button = QPushButton(QIcon.fromTheme("list-add"), "")
        self.add_video_button.setToolTip("Add Custom Video URL")
        self.add_video_button.setFixedWidth(30) # Make it square-ish
        self.add_video_button.clicked.connect(self._add_custom_video)
        search_layout.addWidget(self.add_video_button)
        

        self.import_playlist_button = QPushButton(QIcon.fromTheme("view-list-details", QIcon.fromTheme("document-open")), "")
        self.import_playlist_button.setToolTip("Import YouTube Playlist")
        self.import_playlist_button.setFixedWidth(30) # Same size as add button
        self.import_playlist_button.clicked.connect(self._import_youtube_playlist)
        search_layout.addWidget(self.import_playlist_button)

        middle_layout.addLayout(search_layout)

        self.video_list = QListWidget()
        self.video_list.currentItemChanged.connect(self._on_video_selected)
        middle_layout.addWidget(self.video_list)

        main_splitter.addWidget(middle_widget)

        # --- Right Pane: Player & Details ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5,0,0,0)
        right_widget.setMinimumWidth(400)

        # Video Player
        if WEBENGINE_WIDGETS_AVAILABLE:
            self.video_view = QWebEngineView()
            self.video_view.setMinimumHeight(300)
            self.video_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.video_view.setUrl(QUrl("about:blank"))

            if WEBENGINE_CORE_AVAILABLE:
                settings = self.video_view.settings()
                if settings:
                    try:
                        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
                        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
                        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
                        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
                    except Exception as e: logger.warning(f"Could not set some WebEngine settings: {e}")
                page = self.video_view.page()
                if page: page.loadFinished.connect(self._handle_load_finished)
            right_layout.addWidget(self.video_view, 1)
        else:
            # Fallback if WebEngine is missing
            self.video_view = QLabel("<i>WebEngineView component not found.<br/>Install PySide6-WebEngine to view videos.</i>")
            self.video_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.video_view.setWordWrap(True)
            self.video_view.setMinimumHeight(300)
            self.video_view.setStyleSheet("background-color: #333; color: white; border: 1px solid gray;")
            right_layout.addWidget(self.video_view, 1)

        # Details Box
        details_group = QGroupBox("Details")
        details_layout = QGridLayout(details_group)
        details_layout.setSpacing(8)

        # Row 0
        details_layout.addWidget(QLabel("<b>Author:</b>"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self.author_label = QLabel("N/A")
        self.author_label.setWordWrap(True)
        details_layout.addWidget(self.author_label, 0, 1)
        self.fav_button = QPushButton("")
        self.fav_button.setCheckable(True)
        self.fav_button.setToolTip("Add to/Remove from Favorites")
        self.fav_button.setIconSize(QSize(18,18))
        self.fav_button.setFixedSize(30, 24)
        self.fav_button.clicked.connect(self._toggle_favorite)
        details_layout.addWidget(self.fav_button, 0, 2)
        self.youtube_button = QPushButton(QIcon.fromTheme("browser"), "Open")
        self.youtube_button.setToolTip("Open original URL on YouTube")
        self.youtube_button.clicked.connect(self._open_youtube_link)
        details_layout.addWidget(self.youtube_button, 0, 3)

        # Row 1
        details_layout.addWidget(QLabel("<b>Channel:</b>"), 1, 0, Qt.AlignmentFlag.AlignRight)
        self.channel_label = QLabel("N/A")
        self.channel_label.setWordWrap(True)
        details_layout.addWidget(self.channel_label, 1, 1)
        self.watch_later_button = QPushButton("")
        self.watch_later_button.setCheckable(True)
        self.watch_later_button.setToolTip("Add to/Remove from Watch Later")
        self.watch_later_button.setIconSize(QSize(18,18))
        self.watch_later_button.setFixedSize(30, 24)
        self.watch_later_button.clicked.connect(self._toggle_watch_later)
        details_layout.addWidget(self.watch_later_button, 1, 2)
        self.remove_custom_button = QPushButton(QIcon.fromTheme("edit-delete"), "Remove")
        self.remove_custom_button.setToolTip("Remove this custom video")
        self.remove_custom_button.clicked.connect(self._remove_custom_video)
        self.remove_custom_button.setVisible(False)
        details_layout.addWidget(self.remove_custom_button, 1, 3)

        # Row 2
        details_layout.addWidget(QLabel("<b>Category:</b>"), 2, 0, Qt.AlignmentFlag.AlignRight)
        self.category_label = QLabel("N/A")
        self.category_label.setWordWrap(True)
        details_layout.addWidget(self.category_label, 2, 1, 1, 3) # Span category

        # Row 3 - Added Duration
        details_layout.addWidget(QLabel("<b>Duration:</b>"), 3, 0, Qt.AlignmentFlag.AlignRight)
        self.duration_label = QLabel("N/A")
        details_layout.addWidget(self.duration_label, 3, 1, 1, 3) # Span duration

        # Row 4 (Description)
        desc_label = QLabel("<b>Description:</b>")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        details_layout.addWidget(desc_label, 4, 0)
        self.description_browser = QTextBrowser()
        self.description_browser.setPlaceholderText("Select a video from the list.")
        self.description_browser.setOpenExternalLinks(True)
        self.description_browser.setMinimumHeight(60)
        self.description_browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        details_layout.addWidget(self.description_browser, 4, 1, 1, 3)

        details_layout.setColumnStretch(1, 1)

        right_layout.addWidget(details_group)
        main_splitter.addWidget(right_widget)

        # --- Final Splitter Setup ---
        main_layout.addWidget(main_splitter)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 2)
        main_splitter.setSizes([200, 280, 500])

        self._update_action_buttons_state() # Initialize button states

    # --- Data Loading and Saving ---
    def _load_all_data(self):
        """Loads both curated and user data."""
        logger.info("--- Loading All Classroom Data ---")
        # Load Curated Tutorials
        self.curated_tutorials = []
        curated_path = CONFIG_FILE_CURATED.resolve()
        logger.debug(f"Looking for curated tutorials at: {curated_path}")
        if curated_path.exists():
            try:
                with open(curated_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list): self.curated_tutorials = data
                    else: raise ValueError("Curated data not a list")
                logger.info(f"Loaded {len(self.curated_tutorials)} curated tutorials.")
            except Exception as e: logger.error(f"Failed to load curated tutorials: {e}", exc_info=True)
        else: logger.warning(f"Curated tutorials file not found: {curated_path}")

        # Load User Data
        self.user_data = DEFAULT_USER_DATA.copy()
        user_path = CONFIG_FILE_USER.resolve()
        logger.debug(f"Looking for user data at: {user_path}")
        if user_path.exists():
            try:
                with open(user_path, 'r', encoding='utf-8') as f: data = json.load(f)
                self.user_data["favorites"] = data.get("favorites", []) if isinstance(data.get("favorites"), list) else []
                self.user_data["watch_later"] = data.get("watch_later", []) if isinstance(data.get("watch_later"), list) else []
                self.user_data["my_videos"] = data.get("my_videos", []) if isinstance(data.get("my_videos"), list) else []
                logger.info(f"Loaded user data: {len(self.user_data['favorites'])} favs, {len(self.user_data['watch_later'])} later, {len(self.user_data['my_videos'])} custom.")
            except Exception as e:
                logger.error(f"Failed to load user classroom data: {e}", exc_info=True)
                self.user_data = DEFAULT_USER_DATA.copy()
        else:
            logger.info(f"User classroom data file not found. Using defaults and saving.")
            self._save_user_data()

        self._build_combined_lookup()
        self._populate_nav_list()
        logger.info("--- Finished Loading Classroom Data ---")
        # Use QTimer to ensure UI is fully constructed before setting initial selection
        QTimer.singleShot(0, self._select_initial_nav)

    def _save_user_data(self):
        """Saves user data (favorites, watch later, my_videos) to JSON."""
        try:
            CONFIG_FILE_USER.parent.mkdir(parents=True, exist_ok=True)
            # Ensure values are lists before saving
            save_data = {
                "favorites": list(self.user_data.get("favorites", [])),
                "watch_later": list(self.user_data.get("watch_later", [])),
                "my_videos": self.user_data.get("my_videos", [])
            }
            with open(CONFIG_FILE_USER, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2)
            logger.info(f"User classroom data saved to {CONFIG_FILE_USER}")
        except Exception as e:
            logger.error(f"Failed to save user classroom data: {e}", exc_info=True)

    def _build_combined_lookup(self):
        """Creates the self.combined_videos dictionary from curated and user lists."""
        self.combined_videos = {}
        id_set = set()
        for video in self.curated_tutorials:
            video_id = video.get("id")
            if video_id and video_id not in id_set:
                self.combined_videos[video_id] = video; id_set.add(video_id)
            elif video_id: logger.warning(f"Duplicate curated ID skipped: {video_id}")
            else: logger.warning(f"Curated tutorial missing 'id': {video.get('title')}")
        for video in self.user_data.get("my_videos", []):
            video_id = video.get("id")
            if video_id and video_id not in id_set:
                self.combined_videos[video_id] = video; id_set.add(video_id)
            elif video_id: logger.warning(f"User video ID '{video_id}' conflicts. User version used."); self.combined_videos[video_id] = video
            else: logger.warning(f"User video missing 'id': {video.get('title')}")
        logger.debug(f"Combined video lookup built: {len(self.combined_videos)} entries.")

    # --- UI Population ---
    def _populate_nav_list(self):
        """Populates the left navigation list."""
        self.nav_list.clear()
        self.nav_list.blockSignals(True)
        self.nav_data_map = {
            "All Curated": {"type": "all"}, "Favorites": {"type": "fav"},
            "Watch Later": {"type": "watch"}, "My Videos": {"type": "my"}
        }
        # Add core items
        self.nav_list.addItem(QListWidgetItem(QIcon.fromTheme("view-list-text"), "All Curated"))
        self.nav_list.addItem(QListWidgetItem(QIcon.fromTheme("emblem-favorite"), "Favorites"))
        self.nav_list.addItem(QListWidgetItem(QIcon.fromTheme("document-open-recent"), "Watch Later"))
        self.nav_list.addItem(QListWidgetItem(QIcon.fromTheme("user-home"), "My Videos"))
        
        # Add playlists section if we have any
        playlists = self.user_data.get("playlists", {})
        if playlists:
            separator = QListWidgetItem("--- My Playlists ---")
            separator.setFlags(Qt.ItemFlag.NoItemFlags)
            separator.setForeground(QtGui.QColor("gray"))
            self.nav_list.addItem(separator)
            
            # Add each playlist as a category
            for playlist_id, playlist_info in playlists.items():
                playlist_title = playlist_info.get("title", f"Playlist: {playlist_id}")
                category_name = f"Playlist: {playlist_title}"
                
                item = QListWidgetItem(QIcon.fromTheme("view-media-playlist", QIcon.fromTheme("folder")), category_name)
                self.nav_list.addItem(item)
                self.nav_data_map[category_name] = {
                    "type": "playlist", 
                    "id": playlist_id,
                    "title": playlist_title
                }
        
        # Add curated categories
        curated_categories = sorted(list(set(v.get("category", "Uncategorized") for v in self.curated_tutorials)))
        if curated_categories:
            separator = QListWidgetItem("--- Curated Categories ---")
            separator.setFlags(Qt.ItemFlag.NoItemFlags)
            separator.setForeground(QtGui.QColor("gray"))
            self.nav_list.addItem(separator)
            for category in curated_categories:
                item = QListWidgetItem(QIcon.fromTheme("folder"), category)
                self.nav_list.addItem(item)
                self.nav_data_map[category] = {"type": "category", "name": category}
        self.nav_list.blockSignals(False)

    def _populate_video_list(self):
        """Populates the middle video list based on current nav selection and search."""
        self.video_list.clear()
        self.video_list.blockSignals(True)
        search_term = self.search_input.text().lower().strip()
        nav_info = self.nav_data_map.get(self.current_nav_selection, {"type": "unknown"})
        nav_type = nav_info.get("type")
        logger.debug(f"Populating video list. Nav: '{self.current_nav_selection}' (Type: {nav_type}), Search: '{search_term}'")

        # 1. Get base list based on nav_type
        videos_to_filter = []
        if nav_type == "all": videos_to_filter = self.curated_tutorials
        elif nav_type == "fav": fav_ids = set(self.user_data.get("favorites", [])); videos_to_filter = [v for vid, v in self.combined_videos.items() if vid in fav_ids]
        elif nav_type == "watch": watch_ids = set(self.user_data.get("watch_later", [])); videos_to_filter = [v for vid, v in self.combined_videos.items() if vid in watch_ids]
        elif nav_type == "my": videos_to_filter = self.user_data.get("my_videos", [])
        elif nav_type == "category": category_name = nav_info.get("name"); videos_to_filter = [v for v in self.curated_tutorials if v.get("category") == category_name]
        elif nav_type == "playlist": 
            # For playlists, filter videos by playlist ID and maintain order
            playlist_id = nav_info.get("id")
            playlist_videos = [v for v in self.user_data.get("my_videos", []) 
                            if v.get("playlist", {}).get("id") == playlist_id]
            # Sort by position in playlist
            videos_to_filter = sorted(playlist_videos, 
                                    key=lambda v: v.get("playlist", {}).get("position", 999))
        else: logger.warning(f"Unknown navigation type: {nav_type}"); videos_to_filter = []

        # 2. Apply search filter
        final_videos_to_display = []
        if search_term:
            for video in videos_to_filter:
                match = False
                if search_term in video.get("title", "").lower(): match = True
                if not match and search_term in video.get("description", "").lower(): match = True
                if not match and search_term in video.get("channel_name", "").lower(): match = True
                if not match and search_term in video.get("category", "").lower(): match = True
                if not match and any(search_term in tag.lower() for tag in video.get("tags", [])): match = True
                if match: final_videos_to_display.append(video)
        else: final_videos_to_display = videos_to_filter

        # 3. Populate list widget
        if not final_videos_to_display:
            messages = {
                "fav": "No favorites marked.", 
                "watch": "Watch Later list empty.", 
                "my": "No custom videos added.", 
                "all": "No curated tutorials loaded.",
                "category": f"No videos in '{self.current_nav_selection}'.",
                "playlist": f"No videos found in playlist '{nav_info.get('title')}'."
            }
            placeholder_msg = messages.get(nav_type, "No videos found.")
            if search_term: placeholder_msg = "No videos match search."
            placeholder = QListWidgetItem(placeholder_msg)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            placeholder.setForeground(QtGui.QColor("gray"))
            self.video_list.addItem(placeholder)
        else:
            # Sort videos - by title for normal lists, by position for playlists
            if nav_type == "playlist":
                # Already sorted by position above
                sorted_videos = final_videos_to_display
            else:
                # Default sort by title
                sorted_videos = sorted(final_videos_to_display, key=lambda x: x.get('title','').lower())
                
            # Add items to list
            for video in sorted_videos:
                item = QListWidgetItem(video['title'])
                item.setData(Qt.UserRole, video['id'])
                
                # Add playlist position if we're in a playlist view
                if nav_type == "playlist" and "playlist" in video and "position" in video["playlist"]:
                    item.setText(f"{video['playlist']['position']}. {video['title']}")
                    
                tooltip = video.get('description') or video.get('channel_name') or video['id']
                item.setToolTip(tooltip[:200] + "..." if len(tooltip) > 200 else tooltip)
                self.video_list.addItem(item)

        logger.info(f"Populated video list with {self.video_list.count()} displayable items for '{self.current_nav_selection}'.")
        self.video_list.blockSignals(False)
        # Select first item or clear details
        if self.video_list.count() > 0 and self.video_list.item(0).flags() & Qt.ItemFlag.ItemIsSelectable: self.video_list.setCurrentRow(0)
        else: self._clear_details()

    def _import_youtube_playlist(self):
        """Import videos from a YouTube playlist"""
        dialog = ImportPlaylistDialog(self)
        if dialog.exec() == QDialog.Accepted:
            imported_videos = dialog.get_imported_videos()
            playlist_info = dialog.get_playlist_info()
            
            if not imported_videos:
                QMessageBox.information(self, "Import Result", "No videos were imported from the playlist.")
                return
                
            # Update user data structure to include playlists section if it doesn't exist
            if "playlists" not in self.user_data:
                self.user_data["playlists"] = {}
                
            # Add/update playlist info
            playlist_id = playlist_info["id"]
            playlist_title = playlist_info["title"]
            
            self.user_data["playlists"][playlist_id] = {
                "title": playlist_title,
                "id": playlist_id,
                "video_count": len(imported_videos),
                "date_imported": QtCore.QDateTime.currentDateTime().toString(Qt.DateFormat.ISODate)
            }
                
            # Add the videos to my_videos
            my_videos_list = self.user_data.setdefault("my_videos", [])
            existing_ids = {v.get('id') for v in my_videos_list}
            videos_added = 0
            
            for video in imported_videos:
                video_id = video.get("id")
                # Skip duplicates or update them if needed
                if video_id in existing_ids:
                    # Update existing video entry to ensure it has the latest playlist info
                    for i, existing_video in enumerate(my_videos_list):
                        if existing_video.get('id') == video_id:
                            my_videos_list[i] = video
                            self.combined_videos[video_id] = video
                            logger.info(f"Updated existing video: {video.get('title')} (ID: {video_id})")
                            break
                else:
                    # Add new video
                    my_videos_list.append(video)
                    self.combined_videos[video_id] = video
                    existing_ids.add(video_id)
                    videos_added += 1
                
            # Save changes
            self.user_data["my_videos"] = my_videos_list
            self._save_user_data()
            
            # Rebuild navigation to include new playlist category
            self._populate_nav_list()
            
            # Show results
            QMessageBox.information(
                self, 
                "Import Successful", 
                f"Successfully imported playlist '{playlist_title}'.\n\n"
                f"Added {videos_added} new videos, "
                f"{len(imported_videos) - videos_added} videos updated or skipped."
            )
            
            # Navigate to the newly imported playlist's category
            playlist_category = f"Playlist: {playlist_title}"
            self._select_playlist_category(playlist_category)
                
            logger.info(f"Imported playlist '{playlist_title}' with {videos_added} new videos")
    def _select_playlist_category(self, category_name):
        """Select a specific playlist category in the navigation"""
        # Find category in nav list by name
        for i in range(self.nav_list.count()):
            item = self.nav_list.item(i)
            if item and item.text() == category_name:
                self.nav_list.setCurrentItem(item)
                return
                
        # If not found, try to go to My Videos instead
        my_videos_items = self.nav_list.findItems("My Videos", Qt.MatchFlag.MatchExactly)
        if my_videos_items:
            self.nav_list.setCurrentItem(my_videos_items[0])

    # --- Event Handlers / Slots ---
    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_nav_selected(self, current_item, previous_item):
        """Handles selection change in the navigation list."""
        if not current_item: return
        nav_text = current_item.text()
        if nav_text.startswith("---"): # Ignore separators
            # Optionally re-select the previous valid item if needed
            if previous_item and not previous_item.text().startswith("---"):
                 self.nav_list.setCurrentItem(previous_item)
            return
        self.current_nav_selection = nav_text # Store the display text
        logger.debug(f"Navigation selected: {self.current_nav_selection}")
        self.search_input.clear()
        self._populate_video_list() # Update middle pane

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_video_selected(self, current_item, previous_item):
        """Handles selection change in the video list."""
        self._clear_details()
        if not current_item or not current_item.flags() & Qt.ItemFlag.ItemIsSelectable:
            if WEBENGINE_WIDGETS_AVAILABLE: self.video_view.setUrl(QUrl("about:blank"))
            return

        video_id = current_item.data(Qt.UserRole)
        self.current_video_data = self.combined_videos.get(video_id)

        if not self.current_video_data:
            logger.error(f"Selected video ID '{video_id}' not found in lookup.")
            if WEBENGINE_WIDGETS_AVAILABLE: self.video_view.setUrl(QUrl("about:blank"))
            return

        # Update details
        self.author_label.setText(self.current_video_data.get("author", "N/A"))
        self.channel_label.setText(self.current_video_data.get("channel_name", "N/A"))
        self.category_label.setText(self.current_video_data.get("category", "N/A"))
        self.duration_label.setText(self.current_video_data.get("duration_approx", "N/A"))
        self.description_browser.setPlainText(self.current_video_data.get("description", "No description."))
        self._update_action_buttons_state()

        # Load video
        youtube_id = self.current_video_data.get("youtube_id")
        if youtube_id and WEBENGINE_WIDGETS_AVAILABLE:
            self.video_view.setHtml(self._generate_embed_html(youtube_id), QUrl("https://www.youtube.com"))
            logger.info(f"Loading video: {self.current_video_data.get('title')}")
        elif WEBENGINE_WIDGETS_AVAILABLE:
            self.video_view.setUrl(QUrl("about:blank"))
            logger.warning(f"Tutorial '{self.current_video_data.get('title')}' has no YouTube ID.")

    @Slot()
    def _filter_video_list(self):
        self._populate_video_list()

    @Slot()
    def _toggle_favorite(self):
        if not self.current_video_data: return
        video_id = self.current_video_data["id"]
        fav_list = self.user_data.setdefault("favorites", [])
        fav_set = set(fav_list)
        if video_id in fav_set: fav_set.remove(video_id); logger.info(f"Removed favorite: {video_id}")
        else: fav_set.add(video_id); logger.info(f"Added favorite: {video_id}")
        self.user_data["favorites"] = list(fav_set)
        self._save_user_data()
        self._update_action_buttons_state()
        if self.nav_data_map.get(self.current_nav_selection, {}).get("type") == "fav": self._populate_video_list()

    @Slot()
    def _toggle_watch_later(self):
        if not self.current_video_data: return
        video_id = self.current_video_data["id"]
        watch_list = self.user_data.setdefault("watch_later", [])
        watch_set = set(watch_list)
        if video_id in watch_set: watch_set.remove(video_id); logger.info(f"Removed watch later: {video_id}")
        else: watch_set.add(video_id); logger.info(f"Added watch later: {video_id}")
        self.user_data["watch_later"] = list(watch_set)
        self._save_user_data()
        self._update_action_buttons_state()
        if self.nav_data_map.get(self.current_nav_selection, {}).get("type") == "watch": self._populate_video_list()

    @Slot()
    def _add_custom_video(self):
        dialog = AddVideoDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_video_data = dialog.get_video_data()
            if new_video_data:
                 my_videos_list = self.user_data.setdefault("my_videos", [])
                 if new_video_data["id"] in self.combined_videos: logger.warning(f"ID conflict for custom video: {new_video_data['id']}. Overwriting.")
                 # Remove if editing existing custom video
                 my_videos_list = [v for v in my_videos_list if v.get('id') != new_video_data['id']]
                 my_videos_list.append(new_video_data)
                 self.user_data["my_videos"] = my_videos_list
                 self.combined_videos[new_video_data["id"]] = new_video_data
                 self._save_user_data()
                 # Refresh UI - navigate to "My Videos"
                 my_videos_items = self.nav_list.findItems("My Videos", Qt.MatchFlag.MatchExactly)
                 if my_videos_items:
                      self.nav_list.setCurrentItem(my_videos_items[0]) # Triggers video list refresh via signal
                      QTimer.singleShot(100, lambda: self._select_video_by_id(new_video_data["id"]))
                 logger.info(f"Added/Updated custom video: {new_video_data['title']}")

    @Slot()
    def _remove_custom_video(self):
        if not self.current_video_data or not self.current_video_data.get("is_custom"):
            QMessageBox.warning(self, "Action Failed", "Only custom videos added by you can be removed.")
            return
        video_id = self.current_video_data["id"]; title = self.current_video_data["title"]
        reply = QMessageBox.question(self, "Confirm Remove", f"Remove custom video '{title}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        # Remove from lists and lookup
        self.user_data["my_videos"] = [v for v in self.user_data.get("my_videos", []) if v.get("id") != video_id]
        if video_id in self.combined_videos: del self.combined_videos[video_id]
        fav_set = set(self.user_data.get("favorites", [])); fav_set.discard(video_id); self.user_data["favorites"] = list(fav_set)
        watch_set = set(self.user_data.get("watch_later", [])); watch_set.discard(video_id); self.user_data["watch_later"] = list(watch_set)
        self._save_user_data()
        self._populate_video_list() # Refresh current list (item will disappear)
        logger.info(f"Removed custom video: {title} (ID: {video_id})")

    @Slot()
    def _open_youtube_link(self):
        # (Identical to previous version)
        if self.current_video_data and self.current_video_data.get("url"):
            url = QUrl(self.current_video_data["url"])
            if not QDesktopServices.openUrl(url): logger.error(f"Failed to open URL: {url.toString()}"); QMessageBox.warning(self, "Open URL Failed", f"Could not open URL:\n{url.toString()}")
        else: logger.warning("Attempted to open YouTube link, but no URL found.")

    # --- Helper Methods ---
    def _generate_embed_html(self, youtube_id):
        # (Identical to previous version)
        # Added referrerpolicy and web-share which might help sometimes
        return f"""
        <!DOCTYPE html><html><head><meta charset='utf-8'><title>Video</title></head>
        <body style="margin:0; padding:0; overflow:hidden; background-color:black;">
        <iframe width="100%" height="100%" src="https://www.youtube.com/embed/{youtube_id}?autoplay=0&rel=0"
        frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowfullscreen referrerpolicy="strict-origin-when-cross-origin" style="position:absolute; top:0; left:0; width:100%; height:100%;"></iframe>
        </body></html>"""

    def _clear_details(self):
         self.current_video_data = None
         self.author_label.setText("N/A"); self.channel_label.setText("N/A")
         self.category_label.setText("N/A"); self.duration_label.setText("N/A")
         self.description_browser.setPlainText("Select a video from the list.")
         if WEBENGINE_WIDGETS_AVAILABLE: self.video_view.setUrl(QUrl("about:blank"))
         self._update_action_buttons_state()

    def _update_action_buttons_state(self):
         has_selection = bool(self.current_video_data)
         video_id = self.current_video_data["id"] if has_selection else None
         is_custom = self.current_video_data.get("is_custom", False) if has_selection else False
         fav_set = set(self.user_data.get("favorites", [])); watch_set = set(self.user_data.get("watch_later", []))
         is_favorite = video_id in fav_set; is_watch_later = video_id in watch_set
         # Enable/disable
         self.fav_button.setEnabled(has_selection); self.watch_later_button.setEnabled(has_selection)
         self.youtube_button.setEnabled(has_selection and bool(self.current_video_data.get("url")))
         self.remove_custom_button.setVisible(has_selection and is_custom)
         # Set checked state and icons/tooltips
         fav_icon = "emblem-favorite" if is_favorite else "bookmark-new"; fav_tip = "Remove from Favorites" if is_favorite else "Add to Favorites"
         self.fav_button.setChecked(is_favorite); self.fav_button.setIcon(QIcon.fromTheme(fav_icon, QIcon.fromTheme("starred"))); self.fav_button.setToolTip(fav_tip)
         watch_icon = "document-open-recent" if is_watch_later else "accessories-clock"; watch_tip = "Remove from Watch Later" if is_watch_later else "Add to Watch Later"
         self.watch_later_button.setChecked(is_watch_later); self.watch_later_button.setIcon(QIcon.fromTheme(watch_icon, QIcon.fromTheme("clock"))); self.watch_later_button.setToolTip(watch_tip)

    def _select_video_by_id(self, video_id):
        """Finds and selects a video in the middle list by its ID."""
        for i in range(self.video_list.count()):
             item = self.video_list.item(i)
             if item.data(Qt.UserRole) == video_id:
                  self.video_list.setCurrentItem(item); logger.debug(f"Programmatically selected video: {video_id}"); break
        else: logger.warning(f"Could not find video with ID {video_id} in list to select.")

    # --- Debugging Slots for WebEngine ---
    @Slot(bool)
    def _handle_load_finished(self, ok):
        status = "OK" if ok else "Failed"
        current_url = self.video_view.url().toString() if WEBENGINE_WIDGETS_AVAILABLE else "N/A"
        logger.debug(f"WebEngine page load finished: Status={status}, URL={current_url}")
        if not ok: logger.error(f"WebEngine failed to load content for URL: {current_url}")

    def _select_initial_nav(self):
         """Selects the initial navigation item after UI is ready."""
         all_item = self.nav_list.findItems("All Curated", Qt.MatchFlag.MatchExactly)
         if all_item:
             logger.debug("Setting initial navigation to 'All Curated'")
             self.nav_list.setCurrentItem(all_item[0])
         elif self.nav_list.count() > 0:
             logger.debug("Setting initial navigation to first item")
             # Ensure first item is selectable
             if self.nav_list.item(0).flags() & Qt.ItemFlag.ItemIsSelectable:
                 self.nav_list.setCurrentRow(0)
             else: # Find first selectable item
                 for i in range(self.nav_list.count()):
                     if self.nav_list.item(i).flags() & Qt.ItemFlag.ItemIsSelectable:
                         self.nav_list.setCurrentRow(i)
                         break
         else: logger.warning("Navigation list is empty after loading data.")


# --- Plugin Class (Update initialization) ---
class Plugin(PluginBase):
    """
    Plugin to add an enhanced Scrapy Tutorial Classroom tab.
    """
    def __init__(self):
        super().__init__()
        self.name = "Scrapy Classroom"
        self.description = "View curated/custom tutorials, manage favorites and watch later."
        self.version = "1.2.0" # Version bump
        self.main_window = None
        self.classroom_tab = None
        self._webengine_warning_shown = False # Flag to show warning only once

    def initialize_ui(self, main_window):
        """Create the Enhanced Classroom tab and add it."""
        self.main_window = main_window

        # Check for WebEngine dependency
        if not WEBENGINE_WIDGETS_AVAILABLE or not WEBENGINE_CORE_AVAILABLE:
            dep_type = "Widgets" if not WEBENGINE_WIDGETS_AVAILABLE else "Core"
            logger.error(f"Scrapy Classroom plugin requires PySide6-WebEngine ({dep_type}). Please install it.")
            if not self._webengine_warning_shown:
                QMessageBox.warning(main_window, "Dependency Missing",
                                    f"The 'Scrapy Classroom' plugin requires PySide6-WebEngine ({dep_type} components).\n"
                                    "Video playback will be disabled.\n"
                                    "Please install it (e.g., `pip install PySide6-WebEngine`) and restart.")
                self._webengine_warning_shown = True
            # Continue initialization but video player will be disabled/placeholder

        if hasattr(main_window, 'tab_widget'):
            try:
                # Create the enhanced widget
                self.classroom_tab = EnhancedTutorialClassroomWidget(main_window)
                icon = QIcon.fromTheme("video-display", QIcon.fromTheme("applications-education"))
                main_window.tab_widget.addTab(self.classroom_tab, icon, "Classroom")
                logger.info("Enhanced Scrapy Classroom plugin initialized UI.")
            except Exception as e:
                logger.exception("Failed to initialize Enhanced Scrapy Classroom UI:")
                QMessageBox.critical(main_window, "Plugin Error", f"Failed to initialize Classroom:\n{e}")
        else:
            logger.error("Could not find main window's tab_widget to add Classroom tab.")

    def on_app_exit(self):
        """Clean up resources if necessary."""
        if self.classroom_tab and hasattr(self.classroom_tab, '_save_user_data'):
            self.classroom_tab._save_user_data()
        if self.classroom_tab and hasattr(self.classroom_tab, 'video_view') and WEBENGINE_WIDGETS_AVAILABLE:
            try:
                self.classroom_tab.video_view.stop()
                self.classroom_tab.video_view.setUrl(QUrl("about:blank"))
            except Exception as e: logger.warning(f"Error during Classroom WebEngine cleanup: {e}")
        logger.info("Scrapy Classroom plugin exiting.")