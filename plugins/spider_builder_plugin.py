# plugins/spider_builder_plugin.py
import logging
import os
import re
import keyword # For checking against Python keywords
from urllib.parse import urlparse # For basic URL validation
from pathlib import Path
import time

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLineEdit,
                               QTextEdit, QPlainTextEdit, QGroupBox, QLabel,
                               QPushButton, QMessageBox, QListWidgetItem, QListWidget)
from PySide6.QtGui import QFont, QIcon, QFontDatabase
from PySide6.QtCore import Slot, Qt
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)

# --- Spider Templates ---
SPIDER_TEMPLATES = {
    "Basic": """
import scrapy

class {class_name}(scrapy.Spider):
    name = \"{spider_name}\"
    allowed_domains = [{allowed_domains}]
    start_urls = [{start_urls}]

    def parse(self, response):
        '''
        This method is called for each response downloaded for the start_urls.
        The response object contains the page content and has helpful methods
        for extracting data (like CSS and XPath selectors).
        '''
        self.logger.info(f'Parsing page: {{response.url}}')

        # Example: Extract all links from the page
        # links = response.css('a::attr(href)').getall()
        # for link in links:
        #     yield {{'url': response.urljoin(link)}}

        # --- Your Extraction Logic Below ---
        {extraction_logic}
        # --- End Extraction Logic ---

        # Example: Follow pagination links (if any)
        # next_page = response.css('a.next_page::attr(href)').get()
        # if next_page is not None:
        #     yield response.follow(next_page, self.parse)
        #     self.logger.info(f\"Following next page: {{next_page}}\")
""",
    "CrawlSpider": """
import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import CrawlSpider, Rule

class {class_name}(CrawlSpider):
    name = \"{spider_name}\"
    allowed_domains = [{allowed_domains}]
    start_urls = [{start_urls}]
    rules = (
        Rule(LinkExtractor(allow=()), callback='parse_item', follow=True),
    )
    def parse_item(self, response):
        {extraction_logic}
""",
}

# --- Field Extraction Wizard Dialog (moved to top-level) ---
class FieldExtractionWizardDialog(QtWidgets.QDialog):
    extractionCodeReady = QtCore.Signal(str)
    def __init__(self, parent=None):
        logger.info("[FEW] __init__ start")
        super().__init__(parent)
        self.setWindowTitle("Field Extraction Wizard")
        self.resize(1000, 700)
        self.selected_elements = []
        self.url = ""
        self.html_tree = None
        self.qwebchannel_js = self._load_qwebchannel_js()
        self._init_ui()
        logger.info("[FEW] __init__ end")
        # Start watchdog timer
        self._watchdog_counter = 0
        self._watchdog_timer = QtCore.QTimer(self)
        self._watchdog_timer.timeout.connect(self._watchdog_ping)
        self._watchdog_timer.start(2000)

    def _watchdog_ping(self):
        self._watchdog_counter += 1
        logger.info(f"[FEW] Watchdog ping {self._watchdog_counter}")

    def _load_qwebchannel_js(self):
        logger.info("[FEW] Loading qwebchannel.js")
        static_path = os.path.join(os.path.dirname(__file__), "static", "qwebchannel.js")
        try:
            with open(static_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"[FEW] Failed to load qwebchannel.js: {e}")
            return ""

    def _init_ui(self):
        logger.info("[FEW] _init_ui start")
        layout = QtWidgets.QVBoxLayout(self)
        url_layout = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Enter URL to preview")
        url_layout.addWidget(self.url_input)
        self.fetch_btn = QtWidgets.QPushButton("Fetch")
        self.fetch_btn.clicked.connect(self.fetch_html)
        url_layout.addWidget(self.fetch_btn)
        layout.addLayout(url_layout)
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view, stretch=3)
        selector_layout = QtWidgets.QHBoxLayout()
        self.selector_input = QtWidgets.QLineEdit()
        self.selector_input.setPlaceholderText("CSS or XPath selector (auto-filled on click)")
        selector_layout.addWidget(self.selector_input)
        self.selector_mode_combo = QtWidgets.QComboBox()
        self.selector_mode_combo.addItems(["CSS", "XPath"])
        selector_layout.addWidget(self.selector_mode_combo)
        self.test_btn = QtWidgets.QPushButton("Test Selector")
        self.test_btn.clicked.connect(self.test_selector)
        selector_layout.addWidget(self.test_btn)
        self.add_field_btn = QtWidgets.QPushButton("Add Field")
        self.add_field_btn.clicked.connect(self.add_field)
        selector_layout.addWidget(self.add_field_btn)
        layout.addLayout(selector_layout)
        self.fields_list = QListWidget()
        layout.addWidget(self.fields_list, stretch=1)
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        logger.info("[FEW] _init_ui end")

    def fetch_html(self):
        logger.info("[FEW] Fetch button clicked")
        url = self.url_input.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "Missing URL", "Please enter a URL to fetch.")
            return
        try:
            self.web_view.loadFinished.disconnect(self._inject_js_selector)
        except Exception:
            pass
        self.web_view.loadFinished.connect(self._inject_js_selector)
        self.web_view.load(QtCore.QUrl(url))
        logger.info(f"[FEW] Loading URL: {url}")

    def _inject_js_selector(self):
        logger.info("[FEW] Injecting selector JS into webview")
        try:
            selector_js = """
                (function() {
                    if (window._selectorActive) return;
                    window._selectorActive = true;
                    let lastElem = null;
                    function highlight(elem) {
                        if (lastElem) lastElem.style.outline = '';
                        lastElem = elem;
                        if (elem) elem.style.outline = '2px solid orange';
                    }
                    document.addEventListener('mouseover', function(e) {
                        highlight(e.target);
                    }, true);
                    document.addEventListener('mouseout', function(e) {
                        highlight(null);
                    }, true);
                    document.addEventListener('click', function(e) {
                        e.preventDefault();
                        e.stopPropagation();
                        let path = '';
                        let el = e.target;
                        let tag = el.tagName ? el.tagName.toLowerCase() : '';
                        let attrs = [];
                        if (el.attributes) {
                            for (let i = 0; i < el.attributes.length; i++) {
                                attrs.push(el.attributes[i].name);
                            }
                        }
                        if (window.selectorMode === 'XPath') {
                            path = getXPath(el);
                        } else {
                            path = getCssSelector(el);
                        }
                        let msg = JSON.stringify({selector: path, tag: tag, attrs: attrs});
                        if (window.qt && window.qt.webChannelTransport) {
                            new QWebChannel(qt.webChannelTransport, function(channel) {
                                channel.objects.selectorBridge.elementSelected(msg);
                            });
                        }
                    }, true);
                    function getCssSelector(el) {
                        if (!(el instanceof Element)) return '';
                        let path = [];
                        while (el.nodeType === Node.ELEMENT_NODE) {
                            let selector = el.nodeName.toLowerCase();
                            if (el.id) {
                                selector += '#' + el.id;
                                path.unshift(selector);
                                break;
                            } else {
                                let sib = el, nth = 1;
                                while (sib = sib.previousElementSibling) {
                                    if (sib.nodeName.toLowerCase() == selector)
                                        nth++;
                                }
                                if (nth > 1) selector += ':nth-of-type(' + nth + ')';
                            }
                            path.unshift(selector);
                            el = el.parentNode;
                        }
                        return path.join(' > ');
                    }
                    function getXPath(el) {
                        if (el.id) return '//*[@id="' + el.id + '"]';
                        return getElementTreeXPath(el);
                    }
                    function getElementTreeXPath(element) {
                        const paths = [];
                        for (; element && element.nodeType == 1; element = element.parentNode) {
                            let index = 0;
                            let hasFollowingSiblings = false;
                            for (let sibling = element.previousSibling; sibling; sibling = sibling.previousSibling) {
                                if (sibling.nodeType == Node.DOCUMENT_TYPE_NODE)
                                    continue;
                                if (sibling.nodeName == element.nodeName)
                                    ++index;
                            }
                            for (let sibling = element.nextSibling; sibling && !hasFollowingSiblings; sibling = sibling.nextSibling) {
                                if (sibling.nodeName == element.nodeName)
                                    hasFollowingSiblings = true;
                            }
                            let tagName = element.nodeName.toLowerCase();
                            let pathIndex = (index || hasFollowingSiblings) ? '[' + (index+1) + ']' : '';
                            paths.splice(0, 0, tagName + pathIndex);
                        }
                        return '/' + paths.join('/');
                    }
                })();
            """
            self.web_view.page().runJavaScript(self.qwebchannel_js)
            self.web_view.page().runJavaScript(selector_js)
            class SelectorBridge(QtCore.QObject):
                elementSelectedSignal = QtCore.Signal(str)
                @QtCore.Slot(str)
                def elementSelected(self, msg):
                    self.elementSelectedSignal.emit(msg)
            self.selectorBridge = SelectorBridge()
            self.selectorBridge.elementSelectedSignal.connect(self._on_element_selected)
            self.web_channel = QWebChannel(self.web_view.page())
            self.web_channel.registerObject('selectorBridge', self.selectorBridge)
            self.web_view.page().setWebChannel(self.web_channel)
            logger.info("[FEW] Selector JS and QWebChannel injected successfully")
        except Exception as e:
            logger.error(f"[FEW] Error during JS injection: {e}")

    def _on_element_selected(self, msg):
        logger.info(f"[FEW] Element selected: {msg}")
        import json
        data = json.loads(msg)
        self.selector_input.setText(data['selector'])
        if data['selector'].startswith('/'):
            self.selector_mode_combo.setCurrentText('XPath')
        else:
            self.selector_mode_combo.setCurrentText('CSS')
        # --- Attribute Picker Dialog ---
        tag = data.get('tag', '')
        attrs = data.get('attrs', [])
        attr_options = []
        # Field type detection and attribute suggestion
        if tag == 'img':
            attr_options = ['src', 'alt', 'title', 'text']
            default_attr = 'src'
        elif tag == 'a':
            attr_options = ['href', 'title', 'text']
            default_attr = 'href'
        elif tag == 'input':
            attr_options = ['value', 'name', 'type', 'placeholder', 'text']
            default_attr = 'value'
        else:
            attr_options = [a for a in attrs if a not in ('class', 'style')] + ['text']
            default_attr = 'text'
        attr, ok = QtWidgets.QInputDialog.getItem(self, "Select Attribute", f"Select attribute to extract for <{tag}>:", attr_options, attr_options.index(default_attr) if default_attr in attr_options else 0, False)
        if ok:
            if attr == 'text':
                self.selector_input.setText(data['selector'])
            else:
                if self.selector_mode_combo.currentText() == 'CSS':
                    self.selector_input.setText(f"{data['selector']}::attr({attr})")
                else:
                    # For XPath, append /@attr
                    base_sel = data['selector']
                    if not base_sel.endswith(f"/@{attr}"):
                        self.selector_input.setText(f"{base_sel}/@{attr}")
        self.selected_tag = tag
        self.selected_attr = attr
        self.selected_attrs = attrs

    def add_field(self):
        field = self.selector_input.text().strip()
        mode = self.selector_mode_combo.currentText()
        field_name, ok = QtWidgets.QInputDialog.getText(self, "Field Name", "Enter field name:")
        if not ok or not field_name:
            return
        # Store tag/attr for field type detection
        tag = getattr(self, 'selected_tag', '')
        attr = getattr(self, 'selected_attr', '')
        self.selected_elements.append((field_name, field, mode, tag, attr))
        self.update_fields_list()
        self.selector_input.clear()

    def update_fields_list(self):
        self.fields_list.clear()
        for i, (field_name, selector, mode, tag, attr) in enumerate(self.selected_elements):
            item_text = f"{field_name}: {selector} ({mode}, <{tag}>, {attr})"
            item = QListWidgetItem(item_text)
            remove_btn = QtWidgets.QPushButton("Remove")
            def remove_field(idx=i):
                self.selected_elements.pop(idx)
                self.update_fields_list()
            remove_btn.clicked.connect(remove_field)
            widget = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(widget)
            hbox.addWidget(QtWidgets.QLabel(item_text))
            hbox.addWidget(remove_btn)
            hbox.setContentsMargins(0, 0, 0, 0)
            widget.setLayout(hbox)
            item.setSizeHint(widget.sizeHint())
            self.fields_list.addItem(item)
            self.fields_list.setItemWidget(item, widget)

    def test_selector(self):
        logger.info("[FEW] Test Selector button clicked")
        selector = self.selector_input.text().strip()
        mode = self.selector_mode_combo.currentText()
        if not selector:
            QtWidgets.QMessageBox.warning(self, "Missing Selector", "Enter a selector to test.")
            return
        try:
            from lxml import html
            import requests
            url = self.url_input.text().strip()
            logger.info(f"[FEW] Testing selector '{selector}' on URL '{url}' with mode '{mode}'")
            resp = requests.get(url)
            tree = html.fromstring(resp.content)
            if mode == "CSS":
                results = tree.cssselect(selector)
            else:
                results = tree.xpath(selector)
            QtWidgets.QMessageBox.information(self, "Selector Test", f"Selector matched {len(results)} elements.")
        except Exception as e:
            logger.error(f"[FEW] Error during selector test: {e}")
            QtWidgets.QMessageBox.critical(self, "Selector Error", f"Invalid selector or error:\n{e}")

    def get_extraction_code(self):
        code_lines = []
        for field, selector, mode, tag, attr in self.selected_elements:
            if mode == "CSS":
                sel = selector.strip()
                if sel.endswith('::text') or '::attr(' in sel:
                    code_lines.append(f"item['{field}'] = response.css('{sel}').get()")
                else:
                    code_lines.append(f"item['{field}'] = response.css('{sel}::text').get()")
            else:
                sel = selector.strip()
                if '/@' in sel:
                    code_lines.append(f"item['{field}'] = response.xpath('{sel}').get()")
                else:
                    code_lines.append(f"item['{field}'] = response.xpath('{sel}/text()').get()")
        if code_lines:
            return "item = {}\n" + "\n".join(code_lines) + "\nyield item"
        return "# No fields selected"

    def accept(self):
        logger.info("[FEW] Dialog accepted (Done pressed)")
        code = self.get_extraction_code()
        self.extractionCodeReady.emit(code)
        super().accept()

class SpiderBuilderWidget(QWidget): # Inherit directly from QWidget
    """Widget containing the UI for the Spider Builder tab."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI elements."""
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows) # Ensure labels wrap if needed
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight) # Align labels to the right

        # --- Input Fields ---
        self.spider_name_input = QLineEdit()
        self.spider_name_input.setPlaceholderText("e.g., my_cool_spider (use_snake_case)")
        self.spider_name_input.setToolTip("Required. Use snake_case. Cannot be a Python keyword.")
        form_layout.addRow("Spider Name*:", self.spider_name_input)

        self.allowed_domains_input = QLineEdit()
        self.allowed_domains_input.setPlaceholderText("e.g., example.com, scrapy.org (comma-separated)")
        self.allowed_domains_input.setToolTip("Required. Comma-separated domains, no scheme or path.")
        form_layout.addRow("Allowed Domains*:", self.allowed_domains_input)

        self.start_urls_input = QTextEdit()
        self.start_urls_input.setPlaceholderText("e.g., https://example.com/page1\nhttps://example.com/page2 (one URL per line)")
        self.start_urls_input.setMaximumHeight(100) # Keep height limited
        self.start_urls_input.setAcceptRichText(False) # Ensure plain text
        self.start_urls_input.setToolTip("Required. One valid URL per line.")
        form_layout.addRow("Start URLs*:", self.start_urls_input)

        # --- Spider Type ---
        self.spider_type_combo = QtWidgets.QComboBox()
        self.spider_type_combo.addItems(list(SPIDER_TEMPLATES.keys()))
        self.spider_type_combo.setToolTip("Choose spider base class/template.")
        form_layout.addRow("Spider Type:", self.spider_type_combo)

        # --- Extraction Logic ---
        extraction_group = QGroupBox("Extraction Logic (inserted into spider)")
        extraction_layout = QVBoxLayout(extraction_group)
        self.extraction_logic_input = QPlainTextEdit()
        self.extraction_logic_input.setPlaceholderText(
            "# Optional: Add your extraction code here.\n"
            "# Example using CSS selectors:\n"
            "# items = response.css('div.quote')\n"
            "# for item in items:\n"
            "#     yield {{'text': item.css('span.text::text').get(),\n"
            "#         'author': item.css('small.author::text').get(),\n"
            "#     }}\n"
        )
        self.extraction_logic_input.setToolTip("Python code for the parse method or parse_item (CrawlSpider). Use 'yield' to return data.")
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPointSize(10)
        self.extraction_logic_input.setFont(fixed_font)
        extraction_layout.addWidget(self.extraction_logic_input)

        # --- New Feature: Field Extraction Wizard ---
        self.field_wizard_button = QPushButton(QIcon.fromTheme("system-search"), "Field Extraction Wizard")
        self.field_wizard_button.setToolTip("Open a wizard to visually select fields from a sample URL and auto-generate extraction code.")
        self.field_wizard_button.clicked.connect(self.open_field_extraction_wizard)
        extraction_layout.addWidget(self.field_wizard_button)

        # --- New Feature: Spider Preview ---
        self.preview_spider_button = QPushButton(QIcon.fromTheme("system-run"), "Preview Spider Output")
        self.preview_spider_button.setToolTip("Run the generated spider code on the first URL and preview the output.")
        self.preview_spider_button.clicked.connect(self.preview_spider_output)
        extraction_layout.addWidget(self.preview_spider_button)

        form_layout.addRow(extraction_group)

        layout.addLayout(form_layout)

        # --- Test Extraction Logic Button ---
        self.test_logic_button = QPushButton(QIcon.fromTheme("system-run"), "Test Extraction Logic")
        self.test_logic_button.clicked.connect(self.test_extraction_logic)
        layout.addWidget(self.test_logic_button)

        # --- Tips ---
        tips_group = QGroupBox("Help / Tips")
        tips_layout = QVBoxLayout(tips_group)
        tips_label = QLabel(
            "<ul>"
            "<li><b>Fields marked with * are required.</b></li>"
            "<li><b>Spider Name:</b> Use snake_case (lowercase_with_underscores), cannot be a Python keyword.</li>"
            "<li><b>Allowed Domains:</b> Prevents spider from crawling other sites (e.g., `example.com`).</li>"
            "<li><b>Start URLs:</b> Must be valid URLs (e.g., `https://example.com`).</li>"
            "<li><b>Extraction Logic:</b> Code here will be placed inside the spider's method. Use `yield` to return data.</li>"
            "<li>Use `response.css('selector')` or `response.xpath('selector')` to find elements.</li>"
            "<li>Use `.get()` for one result, `.getall()` for a list.</li>"
            "<li>Get text with `::text`, attributes with `::attr(href)`.</li>"
            "</ul>"
        )
        tips_label.setWordWrap(True)
        tips_layout.addWidget(tips_label)
        layout.addWidget(tips_group)

        # --- Generate Button ---
        self.generate_button = QPushButton(QIcon.fromTheme("document-save"), "Generate Spider File")
        self.generate_button.clicked.connect(self.generate_spider)
        layout.addWidget(self.generate_button)

        layout.addStretch() # Push elements towards the top

    # --- Validation Methods ---
    def _validate_inputs(self, spider_name, allowed_domains_str, start_urls_str):
        """Validate all user inputs."""
        if not spider_name:
            self._show_error("Input Error", "Spider Name cannot be empty.")
            return False, None, None, None
        if not re.match(r"^[a-z_][a-z0-9_]*$", spider_name):
            self._show_error("Input Error", "Spider Name must be a valid Python identifier (snake_case, e.g., my_spider).")
            return False, None, None, None
        if keyword.iskeyword(spider_name):
            self._show_error("Input Error", f"Spider Name '{spider_name}' is a reserved Python keyword.")
            return False, None, None, None

        if not allowed_domains_str:
            self._show_error("Input Error", "Allowed Domains cannot be empty.")
            return False, None, None, None
        domains = [d.strip() for d in allowed_domains_str.split(',') if d.strip()]
        if not domains:
            self._show_error("Input Error", "Allowed Domains cannot be empty after stripping whitespace.")
            return False, None, None, None
        for domain in domains:
             # Basic check: contains a dot, no scheme, no path
             if not ('.' in domain and '://' not in domain and '/' not in domain):
                 self._show_error("Input Error", f"Invalid domain format: '{domain}'. Should be like 'example.com'.")
                 return False, None, None, None
        formatted_domains = ', '.join(f'"{d}"' for d in domains) # Format for template

        if not start_urls_str:
            self._show_error("Input Error", "Start URLs cannot be empty.")
            return False, None, None, None
        urls = [u.strip() for u in start_urls_str.splitlines() if u.strip()]
        if not urls:
            self._show_error("Input Error", "Start URLs cannot be empty after stripping whitespace.")
            return False, None, None, None
        for url in urls:
             try:
                 parsed = urlparse(url)
                 if not parsed.scheme or not parsed.netloc:
                     raise ValueError("Missing scheme or domain")
                 if parsed.scheme not in ('http', 'https'):
                      raise ValueError("Scheme must be http or https")
             except ValueError as e:
                 self._show_error("Input Error", f"Invalid URL format: '{url}'. Reason: {e}")
                 return False, None, None, None
        formatted_urls = ',\n        '.join(f'"{u}"' for u in urls) # Format for template, nice indentation

        return True, spider_name, formatted_domains, formatted_urls

    def _show_error(self, title, message):
        """Helper to show a warning message box."""
        QMessageBox.warning(self, title, message)
        logger.warning(f"{title}: {message}")


    @Slot() # Mark as a PySide6 slot
    def test_extraction_logic(self):
        """Test the extraction logic for syntax errors only."""
        code = self.extraction_logic_input.toPlainText().strip()
        if not code:
            QMessageBox.information(self, "No Code", "Extraction logic is empty.")
            return
        try:
            compile(code, '<extraction_logic>', 'exec')
            QMessageBox.information(self, "Syntax OK", "No syntax errors detected in extraction logic.")
        except SyntaxError as e:
            QMessageBox.critical(self, "Syntax Error", f"Syntax error in extraction logic:\n{e}")

    @Slot() # Mark as a PySide6 slot
    def generate_spider(self):
        """Generate the spider code and save it to a file."""
        logger.info("Generate Spider button clicked.")

        # --- Get Current Project ---
        if not self.main_window.current_project:
            self._show_error("No Project Selected", "Please select a project from the sidebar first.")
            return

        project_path = Path(self.main_window.current_project['path'])
        project_name = self.main_window.current_project.get('name', project_path.name) # Use dir name as fallback
        spiders_dir = project_path / project_name / 'spiders'

        if not spiders_dir.is_dir():
             spiders_dir_alt = project_path / 'spiders'
             if spiders_dir_alt.is_dir():
                  spiders_dir = spiders_dir_alt
             else:
                  self._show_error("Error", f"Could not find spiders directory in project '{project_name}'. Looked in:\n- {spiders_dir}\n- {spiders_dir_alt}")
                  return

        logger.info(f"Target spiders directory: {spiders_dir}")

        # --- Get and Validate Inputs ---
        spider_name_raw = self.spider_name_input.text().strip()
        allowed_domains_str = self.allowed_domains_input.text().strip()
        start_urls_str = self.start_urls_input.toPlainText().strip()
        extraction_logic_raw = self.extraction_logic_input.toPlainText().strip()

        is_valid, spider_name, formatted_domains, formatted_urls = self._validate_inputs(
            spider_name_raw, allowed_domains_str, start_urls_str
        )
        if not is_valid:
            return # Validation failed, error message already shown

        # --- Format Extraction Logic ---
        if extraction_logic_raw:
            # Indent the user's code correctly for the parse method
            indent = " " * 8 # Standard indent inside a method
            indented_extraction_logic = "\n".join(
                [indent + line for line in extraction_logic_raw.splitlines() if line.strip()]
            )
        else:
            # If no logic provided, ensure the template gets 'pass'
            indented_extraction_logic = " " * 8 + "pass"

        # --- Prepare for Code Generation ---
        class_name = "".join(word.capitalize() for word in spider_name.split('_')) + "Spider"

        # --- Get Spider Template ---
        spider_type = self.spider_type_combo.currentText()
        template = SPIDER_TEMPLATES.get(spider_type, SPIDER_TEMPLATES["Basic"])

        # --- Generate Code ---
        try:
            spider_code = template.format(
                class_name=class_name,
                spider_name=spider_name,
                allowed_domains=formatted_domains,
                start_urls=formatted_urls,
                extraction_logic=indented_extraction_logic
            )
        except Exception as fmt_e:
             self._show_error("Code Generation Error", f"Failed to format spider template:\n{fmt_e}")
             logger.exception("Spider template formatting error.")
             return

        # --- Save File ---
        file_path = spiders_dir / f"{spider_name}.py"
        if file_path.exists():
            reply = QMessageBox.question(
                self, "File Exists", f"The file '{file_path.name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                logger.info("Spider generation cancelled by user (file exists).")
                return

        try:
            file_path.write_text(spider_code, encoding='utf-8')
            logger.info(f"Successfully generated spider file: {file_path}")
            self.main_window.statusBar().showMessage(f"Generated spider: {file_path.name}", 5000)

            # --- Post-Generation Actions ---
            self._refresh_main_ui(project_path, file_path)
            # Optionally clear fields after success
            # self.spider_name_input.clear()
            # self.allowed_domains_input.clear()
            # self.start_urls_input.clear()
            # self.extraction_logic_input.clear()

        except OSError as e:
            logger.error(f"Error writing spider file {file_path}: {e}")
            self._show_error("File Error", f"Could not write spider file:\n{e}")
        except Exception as e:
             logger.exception(f"Unexpected error writing spider file {file_path}:")
             self._show_error("File Error", f"An unexpected error occurred:\n{e}")

    def _refresh_main_ui(self, project_path, spider_file_path):
        """Refreshes relevant parts of the main UI after generation."""
        try:
            # Refresh file tree
            if hasattr(self.main_window, 'file_tree') and hasattr(self.main_window.file_tree, 'set_root_path'):
                self.main_window.file_tree.set_root_path(str(project_path))
                logger.debug("Refreshed file tree.")

            # Refresh spider list in the main 'Spiders' tab
            if hasattr(self.main_window, '_refresh_spiders'):
                # Delay slightly to ensure file system changes are reflected
                QtCore.QTimer.singleShot(200, self.main_window._refresh_spiders)
                logger.debug("Scheduled spider list refresh.")

            # Open the new file in the editor
            if hasattr(self.main_window, '_open_file'):
                 # Delay opening slightly after refresh signals if needed
                QtCore.QTimer.singleShot(300, lambda: self.main_window._open_file(str(spider_file_path)))
                logger.debug("Scheduled opening file in editor.")
                # Switch to editor tab
                if hasattr(self.main_window, 'editor_tab') and hasattr(self.main_window, 'tab_widget'):
                     QtCore.QTimer.singleShot(400, lambda: self.main_window.tab_widget.setCurrentWidget(self.main_window.editor_tab))
                     logger.debug("Scheduled switching to editor tab.")

        except Exception as e:
            logger.error(f"Error during post-generation UI refresh: {e}")
            # Don't show a message box here, it's a non-critical failure

    def open_field_extraction_wizard(self):
        logger.info("[FEW] open_field_extraction_wizard called")
        def set_logic(code):
            if code and code != "# No fields selected":
                self.extraction_logic_input.setPlainText(code)
            else:
                QtWidgets.QMessageBox.information(self, "No Fields", "No fields were selected for extraction.")
        dlg = FieldExtractionWizardDialog(self)
        dlg.extractionCodeReady.connect(set_logic)
        dlg.show()
        logger.info("[FEW] open_field_extraction_wizard end")

    def preview_spider_output(self):
        """
        Runs the generated spider code in a dry-run mode on the first start URL and shows output.
        For now, this is a stub. In a full implementation, this would use subprocess to run Scrapy and capture output.
        """
        QMessageBox.information(self, "Spider Preview", "Feature coming soon! This will run the spider and show a preview of the output.")

# --- Plugin Class ---
class Plugin(PluginBase):
    """
    Plugin to add a Spider Builder tab.
    """
    def __init__(self):
        super().__init__()
        self.name = "Spider Builder"
        self.description = "Adds a tab to help create basic Scrapy spiders within the selected project. Now supports multiple templates and logic testing."
        self.version = "2.0.0" # Version bump
        self.main_window = None
        self.builder_widget = None

    def initialize_ui(self, main_window):
        """Create the Spider Builder tab and add it to the main window."""
        self.main_window = main_window

        if hasattr(main_window, 'tab_widget'):
            self.builder_widget = SpiderBuilderWidget(main_window)
            # Add an icon (optional, uses a default Qt icon here)
            icon = QIcon.fromTheme("document-new", QIcon()) # Example icon
            main_window.tab_widget.addTab(self.builder_widget, icon, "Spider Builder")
            logger.info("Spider Builder plugin initialized UI.")
        else:
            logger.error("Could not find main window's tab_widget to add Spider Builder tab.")

    # Optional process methods if needed
    # def process_item(self, item): return item
    # def process_output(self, output): return output
    def on_app_exit(self):
        """Placeholder for cleanup if needed."""
        logger.info("Spider Builder plugin exiting.")