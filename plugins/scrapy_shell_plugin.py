import subprocess
import threading
import logging
import json
from pathlib import Path
from PySide6 import QtWidgets, QtCore, QtGui
from pygments import highlight
from pygments.lexers import PythonLexer, HtmlLexer, JsonLexer
from pygments.formatters import HtmlFormatter
from lxml import etree, html
import webbrowser
from app.plugin_base import PluginBase

logger = logging.getLogger(__name__)


class Plugin(PluginBase):
    name = "Ultimate Scrapy Shell"
    description = "An enhanced interactive Scrapy shell with built-in preview, history, and smart formatting."

    def initialize_ui(self, main_window):
        self.shell_tab = ScrapyShellTab(main_window)
        main_window.tab_widget.addTab(self.shell_tab, "🕷️ Shell")


class ScrapyShellTab(QtWidgets.QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.process = None
        self.history = []
        self.history_index = -1
        self.latest_response = None
        self._init_ui()

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Top controls
        header = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Enter URL (e.g. https://example.com)")
        self.url_input.returnPressed.connect(self.launch_shell)

        self.launch_btn = QtWidgets.QPushButton("Launch")
        self.launch_btn.clicked.connect(self.launch_shell)

        self.docs_btn = QtWidgets.QPushButton("Scrapy Docs")
        self.docs_btn.clicked.connect(lambda: webbrowser.open("https://docs.scrapy.org/en/latest/topics/shell.html"))

        header.addWidget(self.url_input)
        header.addWidget(self.launch_btn)
        header.addWidget(self.docs_btn)
        layout.addLayout(header)

        # Shell output
        self.output = QtWidgets.QTextBrowser()
        self.output.setStyleSheet("background-color: #1e1e1e; color: #dcdcdc; font-family: Consolas;")
        layout.addWidget(self.output)

        # Command input row
        command_row = QtWidgets.QHBoxLayout()
        self.command_input = QtWidgets.QLineEdit()
        self.command_input.setPlaceholderText(">>> Type a command")
        self.command_input.setDisabled(True)
        self.command_input.returnPressed.connect(self.send_command)
        self.command_input.installEventFilter(self)

        self.preview_button = QtWidgets.QPushButton("Preview response.text")
        self.preview_button.clicked.connect(self.preview_response_text)
        self.preview_button.setDisabled(True)

        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.clicked.connect(self.output.clear)

        command_row.addWidget(self.command_input)
        command_row.addWidget(self.preview_button)
        command_row.addWidget(self.clear_btn)
        layout.addLayout(command_row)

        # Response preview
        preview_label = QtWidgets.QLabel("🖼️ Response Preview")
        preview_label.setStyleSheet("font-weight: bold; padding-top: 8px;")
        layout.addWidget(preview_label)

        self.preview = QtWidgets.QTextBrowser()
        self.preview.setMinimumHeight(160)
        self.preview.setStyleSheet("background-color: #f5f5f5; color: #333; font-family: Consolas;")
        layout.addWidget(self.preview)

    def launch_shell(self):
        url = self.url_input.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "URL Missing", "Please enter a URL to launch Scrapy shell.")
            return

        self.stop_shell()
        self.output.append(f"<b style='color:#6cf;'>Launching Scrapy shell for:</b> {url}")

        try:
            self.process = subprocess.Popen(
                ["scrapy", "shell", url],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            self.command_input.setDisabled(False)
            self.preview_button.setDisabled(False)

            self.reader_thread = threading.Thread(target=self.read_output, daemon=True)
            self.reader_thread.start()
        except Exception as e:
            self.output.append(f"<span style='color:red;'>Failed to launch Scrapy shell: {e}</span>")
            logger.error(f"Shell error: {e}")

    def stop_shell(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
                self.output.append("<b style='color:orange;'>Shell terminated.</b>")
            except Exception as e:
                logger.warning(f"Could not terminate shell: {e}")
            self.process = None

    def send_command(self):
        command = self.command_input.text().strip()
        if not command or not self.process:
            return

        self.output.append(f"<b>>>> {command}</b>")
        self.history.append(command)
        self.history_index = len(self.history)

        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
        except Exception as e:
            self.output.append(f"<span style='color:red;'>Error sending command: {e}</span>")

        self.command_input.clear()

    def read_output(self):
        try:
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    html_line = self._highlight(line.rstrip())
                    QtCore.QMetaObject.invokeMethod(
                        self.output,
                        "append",
                        QtCore.Qt.QueuedConnection,
                        QtCore.Q_ARG(str, html_line)
                    )
        except Exception as e:
            logger.error(f"Error reading output: {e}")

    def _highlight(self, text):
        try:
            lexer = PythonLexer()
            formatter = HtmlFormatter(noclasses=True, style="friendly")
            return highlight(text, lexer, formatter)
        except:
            return text

    def preview_response_text(self):
        """
        Calls `scrapy shell` again with the same URL in a subprocess
        and evaluates response.text to render in preview.
        """
        url = self.url_input.text().strip()
        if not url:
            return

        self.preview.setPlainText("Loading preview...")
        thread = threading.Thread(target=self._run_preview_scrapy_shell, args=(url,))
        thread.start()

    def _run_preview_scrapy_shell(self, url):
        try:
            process = subprocess.Popen(
                ["scrapy", "shell", url, "-c", "print(response.text)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            output, _ = process.communicate(timeout=10)
            parsed = self._try_prettify_html(output)
            QtCore.QMetaObject.invokeMethod(
                self.preview,
                "setPlainText",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, parsed.strip())
            )
        except subprocess.TimeoutExpired:
            QtCore.QMetaObject.invokeMethod(
                self.preview,
                "setPlainText",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, "Timed out.")
            )
        except Exception as e:
            logger.error(f"Preview error: {e}")
            QtCore.QMetaObject.invokeMethod(
                self.preview,
                "setPlainText",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, f"Error fetching preview: {e}")
            )

    def _try_prettify_html(self, raw):
        try:
            doc = html.fromstring(raw)
            return etree.tostring(doc, pretty_print=True, encoding="unicode")
        except:
            return raw

    def eventFilter(self, obj, event):
        if obj == self.command_input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Up:
                self.history_index = max(0, self.history_index - 1)
                self.command_input.setText(self.history[self.history_index])
                return True
            elif event.key() == QtCore.Qt.Key_Down:
                self.history_index = min(len(self.history) - 1, self.history_index + 1)
                if self.history_index < len(self.history):
                    self.command_input.setText(self.history[self.history_index])
                return True
        return super().eventFilter(obj, event)
