import logging
import sys
from pathlib import Path
import json

# Import necessary PySide6 components
# Added QApplication
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QLineEdit,
                               QPushButton, QTextBrowser, QFrame, QGroupBox, QFormLayout,
                               QLabel, QTextEdit, QDialog, QDialogButtonBox, QMessageBox,
                               QApplication)

# Added QWebChannel, QObject, Signal, QWebEngineScript
from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt, Slot, QUrl, QObject, Signal
# Added QWebEngineScript and ScriptWorldId
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                     QWebEngineScript, QWebEngineSettings,
                                     QWebEngineScriptCollection)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel # Added
from PySide6.QtGui import QAction, QIcon
from PySide6 import QtWidgets
# Import Plugin Base and potentially other app components if needed
from app.plugin_base import PluginBase
import site # Added for finding site-packages

# HTML/Selector parsing (use Scrapy's underlying library or lxml)
try:
    from parsel import Selector
    USE_PARSEL = True
except ImportError:
    try:
        from lxml import html as lxml_html
        USE_PARSEL = False
        logging.warning("Parsel not found, falling back to lxml for selector testing.")
    except ImportError:
        USE_PARSEL = False
        logging.error("Neither parsel nor lxml found. Selector testing will be disabled.")
        # Optionally disable the feature entirely in the UI if neither is available

# Syntax Highlighting
try:
    from pygments import highlight
    from pygments.lexers import HtmlLexer
    from pygments.formatters import HtmlFormatter
    USE_PYGMENTS = True
except ImportError:
    USE_PYGMENTS = False
    logging.warning("Pygments not found. HTML source view will not be highlighted.")

logger = logging.getLogger(__name__)

# --- Standard qwebchannel.js Source Code ---
# Embed directly to avoid file loading issues across environments
QWEBCHANNEL_JS_CODE = """
/****************************************************************************
**
** Copyright (C) 2021 The Qt Company Ltd.
** Contact: https://www.qt.io/licensing/
**
** This file is part of the QtWebChannel module of the Qt Toolkit.
**
** $QT_BEGIN_LICENSE:BSD$
** Commercial License Usage
** Licensees holding valid commercial Qt licenses may use this file in
** accordance with the commercial license agreement provided with the
** Software or, alternatively, in accordance with the terms contained in
** a written agreement between you and The Qt Company. For licensing terms
** and conditions see https://www.qt.io/terms-conditions. For further
** information use the contact form at https://www.qt.io/contact-us.
**
** BSD License Usage
** Alternatively, you may use this file under the terms of the BSD license
** as follows:
**
** "Redistribution and use in source and binary forms, with or without
** modification, are permitted provided that the following conditions are
** met:
**   * Redistributions of source code must retain the above copyright
**     notice, this list of conditions and the following disclaimer.
**   * Redistributions in binary form must reproduce the above copyright
**     notice, this list of conditions and the following disclaimer in
**     the documentation and/or other materials provided with the
**     distribution.
**   * Neither the name of The Qt Company Ltd nor the names of its
**     contributors may be used to endorse or promote products derived
**     from this software without specific prior written permission.
**
**
** THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
** "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
** LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
** A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
** OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
** SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
** LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
** DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
** THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
** (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
** OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."
**
** $QT_END_LICENSE$
**
****************************************************************************/

"use strict";

class QWebChannel {
    constructor(transport, initCallback) {
        if (typeof transport !== 'object' || typeof transport.send !== 'function') {
            console.error("The QWebChannel transport object is invalid.");
            return;
        }

        this.transport = transport;
        this.initCallback = initCallback;
        this.execCallbacks = {};
        this.execId = 0;
        this.objects = {};

        this.transport.onmessage = this._handleMessage.bind(this);

        this._send({ type: QWebChannelMessageTypes.init });
    }

    _send(data) {
        if (typeof data !== 'string') {
            data = JSON.stringify(data);
        }
        this.transport.send(data);
    }

    _handleMessage(message) {
        let data = message.data;
        if (typeof data === 'string') {
            data = JSON.parse(data);
        }

        switch (data.type) {
            case QWebChannelMessageTypes.signal:
                this._handleSignal(data);
                break;
            case QWebChannelMessageTypes.response:
                this._handleResponse(data);
                break;
            case QWebChannelMessageTypes.init:
                this._handleInit(data);
                break;
            default:
                console.error("Unknown message received:", data);
                break;
        }
    }

    _handleSignal(data) {
        const object = this.objects[data.object];
        if (object) {
            const signal = object.signals[data.signal];
            if (signal) {
                signal(...data.args);
            } else {
                console.error(`Signal ${data.signal} not found on object ${data.object}`);
            }
        } else {
            console.error(`Object ${data.object} not found for signal`);
        }
    }

    _handleResponse(data) {
        const callback = this.execCallbacks[data.id];
        if (callback) {
            callback(data.data);
            delete this.execCallbacks[data.id];
        } else {
            console.warn(`No callback found for response id: ${data.id}`);
        }
    }

    _handleInit(data) {
        for (const objectName in data.data) {
            this.objects[objectName] = new QObject(objectName, data.data[objectName], this);
        }
        if (this.initCallback) {
            this.initCallback(this);
        }
        // Clean up callback after initialization
        this.initCallback = null;
    }

    exec(data, callback) {
        if (!callback) {
            // Fire and forget
            this._send(data);
            return;
        }
        if (this.execId === Number.MAX_SAFE_INTEGER) {
            this.execId = 0;
        }
        const id = ++this.execId;
        data.id = id;
        this.execCallbacks[id] = callback;
        this._send(data);
    }
}

// Message types
const QWebChannelMessageTypes = {
    signal: 1,
    propertyUpdate: 2,
    init: 3,
    idle: 4,
    debug: 5,
    invokeMethod: 6,
    connectToSignal: 7,
    disconnectFromSignal: 8,
    setProperty: 9,
    response: 10
};

// Helper class representing a QObject proxy
class QObject {
    constructor(name, data, webChannel) {
        this.__id__ = name;
        this.__webChannel__ = webChannel;
        this.methods = {};
        this.properties = {};
        this.signals = {};

        // Initialize methods
        data.methods.forEach(methodData => {
            this[methodData[0]] = (...args) => {
                const message = {
                    type: QWebChannelMessageTypes.invokeMethod,
                    object: this.__id__,
                    method: methodData[0],
                    args: args
                };
                let callback;
                if (typeof args[args.length - 1] === 'function') {
                    callback = args.pop();
                }
                this.__webChannel__.exec(message, callback);
            };
            this.methods[methodData[0]] = methodData[1]; // Store return type if needed
        });

        // Initialize properties
        data.properties.forEach(propData => {
            const propName = propData[0];
            this.properties[propName] = propData[1]; // Store type info
            Object.defineProperty(this, propName, {
                configurable: true,
                get: () => {
                    // Reading property value requires async call in some implementations
                    // For simplicity here, we assume direct access or cached value if available
                    // A robust implementation might need a getProperty method call
                    console.warn(`Property read for ${propName} might be asynchronous.`);
                    return this.properties[propName]; // Return cached/initial type info for now
                },
                set: (value) => {
                    this.properties[propName] = value; // Update local cache/type
                    this.__webChannel__.exec({
                        type: QWebChannelMessageTypes.setProperty,
                        object: this.__id__,
                        property: propName,
                        value: value
                    });
                }
            });
        });

        // Initialize signals
        data.signals.forEach(signalData => {
            const signalName = signalData[0];
            this.signals[signalName] = (...args) => {
                // This function is called by the webchannel when the signal is received
                // Users connect to this signal object directly
                if (this.signals[signalName].callbacks) {
                    this.signals[signalName].callbacks.forEach(callback => {
                        callback(...args);
                    });
                }
            };
            this.signals[signalName].callbacks = []; // Store user callbacks here
            this.signals[signalName].connect = (callback) => {
                if (typeof callback !== 'function') {
                    console.error("Cannot connect non-function to signal " + signalName);
                    return;
                }
                if (this.signals[signalName].callbacks.length === 0) {
                    // First connection, notify C++ side
                    this.__webChannel__.exec({
                        type: QWebChannelMessageTypes.connectToSignal,
                        object: this.__id__,
                        signal: signalName
                    });
                }
                this.signals[signalName].callbacks.push(callback);
            };
            this.signals[signalName].disconnect = (callback) => {
                const index = this.signals[signalName].callbacks.indexOf(callback);
                if (index !== -1) {
                    this.signals[signalName].callbacks.splice(index, 1);
                    if (this.signals[signalName].callbacks.length === 0) {
                        // Last connection removed, notify C++ side
                        this.__webChannel__.exec({
                            type: QWebChannelMessageTypes.disconnectFromSignal,
                            object: this.__id__,
                            signal: signalName
                        });
                    }
                } else {
                    console.warn("Cannot disconnect function not connected to signal " + signalName);
                }
            };
        });

        // Initialize enums (if any)
        // data.enums...
    }
}

// Make QWebChannel available globally if running in a browser environment
if (typeof window === 'object') {
    window.QWebChannel = QWebChannel;
}
"""

# --- Inspector JavaScript Code (Direct Embedding) ---
# Instead of loading from a file, embed the JS directly
INSPECT_ELEMENT_JS_CODE = """
// Script for element inspection within QWebEngineView for Scrapy Browser Plugin

console.log('[Inspector.js] Script loading...');

// Use an IIFE (Immediately Invoked Function Expression) to avoid polluting the global scope
(function() {
    console.log('[Inspector.js] IIFE executing...');

    let currentHighlight = null;    // The currently highlighted element
    let inspectorActive = false;    // Flag to indicate if inspector mode is on
    let overlay = null;             // Reference to the semi-transparent overlay div

    // --- Create Overlay Div (Optional visual indicator) ---
    function createOverlay() {
        const div = document.createElement('div');
        div.id = '__scrapyInspectorOverlay';
        div.style.position = 'fixed';
        div.style.top = '0';
        div.style.left = '0';
        div.style.width = '100%';
        div.style.height = '100%';
        div.style.backgroundColor = 'rgba(0, 100, 200, 0.1)'; // Light blue tint
        div.style.zIndex = '99999998'; // Very high z-index, below highlight
        div.style.pointerEvents = 'none'; // Let clicks pass through
        div.style.display = 'none'; // Initially hidden
        document.body.appendChild(div);
        console.log('[Inspector.js] Overlay created.');
        return div;
    }

    // --- Event Handlers ---
    function mouseOverHandler(event) {
        if (!inspectorActive) return;

        const target = event.target;
        if (target && target !== currentHighlight && target.id !== '__scrapyInspectorOverlay') {
            // Remove highlight from previous element
            if (currentHighlight) {
                currentHighlight.style.outline = '';
                 currentHighlight.style.boxShadow = ''; // Remove potential box shadow
                 currentHighlight.style.zIndex = '';
            }
            // Apply highlight to new element
            target.style.outline = '2px dashed red';
            target.style.outlineOffset = '-2px'; // Offset inside element bounds
            target.style.boxShadow = '0 0 5px 2px rgba(255, 0, 0, 0.5)'; // Optional glow
            target.style.zIndex = '99999999'; // Ensure highlight is on top
            currentHighlight = target;
        }
    }

    function mouseOutHandler(event) {
        if (!inspectorActive) return;

        // Only remove highlight if the mouse truly left the element
        // This check helps with nested elements
        if (currentHighlight && event.relatedTarget !== currentHighlight && !currentHighlight.contains(event.relatedTarget)) {
             currentHighlight.style.outline = '';
             currentHighlight.style.boxShadow = '';
             currentHighlight.style.zIndex = '';
             currentHighlight = null;
        }
    }

    function clickHandler(event) {
        if (!inspectorActive) return;

        console.log('[Inspector.js] clickHandler activated.');
        event.preventDefault();
        event.stopPropagation(); // Stop the click from propagating further

        const target = event.target;
        if (target && target.id !== '__scrapyInspectorOverlay') {
            console.log('[Inspector.js] Target element identified:', target);
            try {
                const selector = getCssSelector(target);
                const info = {
                    tag: target.tagName.toLowerCase(),
                    id: target.id || null,
                    classes: target.className || null,
                    attributes: {},
                    text: target.textContent.trim().substring(0, 200) + (target.textContent.trim().length > 200 ? '...' : ''), // Limit text preview
                    css_selector: selector
                };

                // Get attributes
                for (let i = 0; i < target.attributes.length; i++) {
                    const attr = target.attributes[i];
                    info.attributes[attr.name] = attr.value;
                }

                console.log('[Inspector.js] Element info gathered:', info);

                // Send data back to Python via the bridge
                if (window.inspectorBridge && typeof window.inspectorBridge.elementClicked === 'function') {
                    const jsonInfo = JSON.stringify(info);
                    console.log('[Inspector.js] Sending data to Python bridge:', jsonInfo.substring(0, 300) + '...');
                    window.inspectorBridge.elementClicked(jsonInfo);
                } else {
                    console.error('[Inspector.js] Cannot send data: inspectorBridge or elementClicked method not found on window.');
                }

                // Optionally stop inspecting after one click? Or keep it active?
                // stopScrapyInspector(); // Uncomment to stop after first click
                // Or maybe just remove the highlight after click
                if (currentHighlight) {
                    currentHighlight.style.outline = '';
                    currentHighlight.style.boxShadow = '';
                    currentHighlight.style.zIndex = '';
                    currentHighlight = null;
                }

            } catch (e) {
                console.error("[Inspector.js] Error during click handling:", e);
                // Optionally inform Python about the error?
            }
        } else {
             console.log('[Inspector.js] Click ignored (target is overlay or invalid).');
        }
        return false; // Further attempt to block default action
    }

    // --- CSS Selector Generation ---
    // Basic CSS Selector generation function (can be improved)
    function getCssSelector(el) {
        if (!(el instanceof Element)) return null;
        let path = [];
        while (el.nodeType === Node.ELEMENT_NODE) {
            let selector = el.nodeName.toLowerCase();
            if (el.id) {
                // Escape potential special characters in ID
                const escapedId = el.id.replace(/([!"#$%&'()*+,./:;<=>?@[\\\]^`{|}~])/g, '\\$1');
                selector += '#' + escapedId;
                path.unshift(selector);
                break; // ID is unique enough
            } else {
                let sib = el, nth = 1;
                while (sib = sib.previousElementSibling) {
                    if (sib.nodeName.toLowerCase() == selector)
                       nth++;
                }
                if (nth != 1)
                    selector += ":nth-of-type("+nth+")";
            }
            path.unshift(selector);
            el = el.parentNode;
            if (el === document.body) break; // Stop at body
        }
        return path.join(" > ");
    }


    // --- Main Control Functions (Globally Accessible) ---
    window.startScrapyInspector = function() {
        if (inspectorActive) {
            console.log('[Inspector.js] Inspector already active.');
            return;
        }
        console.log('[Inspector.js] Starting inspector...');
        if (!overlay) {
            // Lazy creation in case body wasn't ready when script first ran
            if (document.body) {
                 overlay = createOverlay();
            } else {
                 console.warn('[Inspector.js] Cannot create overlay: document.body not ready yet.');
                 // Try again later maybe? Or rely solely on outline highlight.
                 document.addEventListener('DOMContentLoaded', () => {
                     if (!overlay) overlay = createOverlay();
                     if (overlay && inspectorActive) overlay.style.display = 'block';
                 });
            }
        }
        if (overlay) {
             overlay.style.display = 'block'; // Show overlay
        }
        // Attach listeners using capture phase
        document.addEventListener('mouseover', mouseOverHandler, true);
        document.addEventListener('mouseout', mouseOutHandler, true);
        document.addEventListener('click', clickHandler, true);
        inspectorActive = true;
        console.log('[Inspector.js] Inspector started and listeners attached.');
    };

    window.stopScrapyInspector = function() {
        if (!inspectorActive) {
            console.log('[Inspector.js] Inspector already stopped.');
            return;
        }
        console.log('[Inspector.js] Stopping inspector...');
        // Remove listeners
        document.removeEventListener('mouseover', mouseOverHandler, true);
        document.removeEventListener('mouseout', mouseOutHandler, true);
        document.removeEventListener('click', clickHandler, true);

        // Remove any lingering highlight
        if (currentHighlight) {
            try { // Add try-catch just in case element became invalid
                currentHighlight.style.outline = '';
                currentHighlight.style.boxShadow = '';
                currentHighlight.style.zIndex = '';
            } catch (e) { console.warn('[Inspector.js] Error removing highlight from stale element:', e); }
            currentHighlight = null;
        }
        // Hide overlay
        if (overlay) {
            overlay.style.display = 'none';
        }
        inspectorActive = false;
        console.log('[Inspector.js] Inspector stopped and listeners removed.');
    };

    // --- Live Selector Testing Function (Globally Accessible) ---
    window.testSelectorLive = function(selector, type, requestId) {
        console.log(`[Inspector.js] testSelectorLive called. Type: ${type}, Selector: ${selector}, Request ID: ${requestId}`);
        let results = [];
        let error = null;
        try {
            if (type === 'css') {
                document.querySelectorAll(selector).forEach(el => {
                    // Extract outerHTML or specific text/attribute for preview
                    results.push(el.outerHTML.substring(0, 150) + (el.outerHTML.length > 150 ? '...' : ''));
                });
            } else if (type === 'xpath') {
                const xpathResult = document.evaluate(selector, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                for (let i = 0; i < xpathResult.snapshotLength; i++) {
                    const node = xpathResult.snapshotItem(i);
                    // Handle potential text nodes from XPath
                    let preview = node.nodeType === Node.TEXT_NODE
                                  ? node.textContent
                                  : node.outerHTML;
                    results.push(preview.substring(0, 150) + (preview.length > 150 ? '...' : ''));
                }
            } else {
                throw new Error("Invalid selector type specified (must be 'css' or 'xpath').");
            }
            console.log(`[Inspector.js] Found ${results.length} results for request ${requestId}.`);
        } catch (e) {
            console.error(`[Inspector.js] Error testing live selector (${type}, ID: ${requestId}, Selector: ${selector}):`, e);
            error = e.toString(); // Send error message back
        }
        // Send results back via the bridge
        try {
            if (window.inspectorBridge && typeof window.inspectorBridge.liveSelectorResults === 'function') {
                 const jsonResults = JSON.stringify(results);
                 window.inspectorBridge.liveSelectorResults(requestId, jsonResults, error || "");
                 console.log(`[Inspector.js] Sent results (or error) for request ${requestId} back to Python.`);
            } else {
                 console.error("[Inspector.js] Cannot send live results back: inspectorBridge or liveSelectorResults method not found.");
                 // If the bridge isn't ready, we can't send the results back.
                 // This might happen if called too early. Python side won't get a response.
            }
        } catch(bridgeError) {
            console.error("[Inspector.js] Error calling Python bridge for live results:", bridgeError);
        }
    };

    console.log('[Inspector.js] IIFE finished. Global functions attached to window object.');

})(); // End of IIFE

console.log('[Inspector.js] Script fully parsed and executed.');
"""

# --- QWebChannel Bridge Object ---
class InspectorBridge(QObject):
    elementInfoReceived = Signal(dict)
    liveSelectorResults = Signal(int, str, str)

    @Slot(str)
    def elementClicked(self, json_info):
        logger.debug(f"InspectorBridge received raw data: {json_info[:200]}...")
        try:
            info = json.loads(json_info)
            self.elementInfoReceived.emit(info)
        except Exception as e:
            logger.error(f"Error processing elementClicked data: {e}")

    @Slot(str)
    def logError(self, message):
        logger.error(f"[JS Error Callback] {message}")


class HtmlViewDialog(QtWidgets.QDialog):
    """Dialog to display syntax-highlighted HTML."""
    def __init__(self, html_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rendered HTML Source")
        self.setMinimumSize(800, 600)

        layout = QtWidgets.QVBoxLayout(self)
        self.text_browser = QtWidgets.QTextBrowser()
        self.text_browser.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))

        if USE_PYGMENTS:
            try:
                formatter = HtmlFormatter(noclasses=True, style='default') # Use default style for better theme compatibility
                highlighted_html = highlight(html_content, HtmlLexer(), formatter)
                # Add basic HTML structure for display in QTextBrowser
                # Include basic CSS for background/foreground that matches theme potentially
                # For simplicity, we let pygments handle colors via its style
                full_doc = f"""
                <!DOCTYPE html>
                <html><head><meta charset='utf-8'>
                <style>{formatter.get_style_defs('.highlight')}</style>
                </head><body>
                <div class="highlight"><pre>{highlighted_html}</pre></div>
                </body></html>"""
                self.text_browser.setHtml(full_doc)
            except Exception as e:
                logger.error(f"Pygments highlighting failed: {e}")
                self.text_browser.setPlainText(html_content) # Fallback
        else:
            self.text_browser.setPlainText(html_content)

        layout.addWidget(self.text_browser)

        # Add a close button
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

# --- Main Browser Widget ---
class ScrapyBrowserTab(QtWidgets.QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.html_content = ""
        self.inspect_mode = False
        self.inspected_css_selector = None
        self.live_test_requests = {}
        self.selector_libs_ok = USE_PARSEL or 'lxml_html' in globals()
        self.pygments_ok = USE_PYGMENTS
        self.js_initialized = False # Flag to track if core JS has been run for the current page

        # --- Initialize UI first ---
        self._init_ui() # Creates self.page

        # --- QWebChannel Setup ---
        self.inspector_bridge = InspectorBridge()
        self.channel = QWebChannel(self)
        self.channel.registerObject("inspectorBridge", self.inspector_bridge)
        logger.debug("InspectorBridge and QWebChannel objects created.")

        # --- Set WebChannel on the page ---
        # Do this EARLY, before loading any content
        self.page.setWebChannel(self.channel)
        logger.info("WebChannel set on page.")

        # --- Initialize signals ---
        self._setup_signals()

        # Buttons start disabled
        self.inspect_button.setEnabled(False)

        self.web_view.setUrl(QUrl("about:blank"))

    def _init_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0) # Use full space

        # --- Browser Area ---
        browser_container = QtWidgets.QWidget()
        browser_layout = QtWidgets.QVBoxLayout(browser_container)
        browser_layout.setContentsMargins(5, 5, 5, 5)
        browser_layout.setSpacing(5)

        # Navigation Toolbar
        nav_toolbar = QtWidgets.QToolBar("Navigation")
        # Use standard icons if available, otherwise use text
        self.back_action = nav_toolbar.addAction(QIcon.fromTheme("go-previous", QIcon()), "Back")
        self.forward_action = nav_toolbar.addAction(QIcon.fromTheme("go-next", QIcon()), "Forward")
        self.reload_action = nav_toolbar.addAction(QIcon.fromTheme("view-refresh", QIcon()), "Reload")
        self.stop_action = nav_toolbar.addAction(QIcon.fromTheme("process-stop", QIcon()), "Stop")
        nav_toolbar.addSeparator()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Enter URL and press Enter")
        nav_toolbar.addWidget(self.url_input)

        browser_layout.addWidget(nav_toolbar)

        # Web View
        self.web_view = QWebEngineView()
        self.page = QWebEnginePage() # Create the page object
        self.web_view.setPage(self.page) 
        # Enable JavaScript and other settings
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        
        # Create the page object
        self.page = QWebEnginePage()
        self.web_view.setPage(self.page)
        
        browser_layout.addWidget(self.web_view)

        main_layout.addWidget(browser_container, 7) # Browser takes 70% width

        # --- Helper Panel ---
        helper_panel = QtWidgets.QFrame()
        helper_panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        helper_layout = QtWidgets.QVBoxLayout(helper_panel)
        helper_layout.setContentsMargins(5, 5, 5, 5)
        helper_layout.setSpacing(10)

        helper_title = QtWidgets.QLabel("Scrapy Helper Tools")
        helper_title.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 5px;")
        helper_layout.addWidget(helper_title)

        # Element Inspector
        inspector_group = QtWidgets.QGroupBox("Element Inspector")
        inspector_layout = QtWidgets.QVBoxLayout(inspector_group)
        self.inspect_button = QtWidgets.QPushButton("Toggle Inspect Element")
        self.inspect_button.setCheckable(True)
        self.inspect_button.setToolTip("Click then click elements on the page to get info")
        self.element_info_display = QtWidgets.QTextEdit()
        self.element_info_display.setReadOnly(True)
        self.element_info_display.setPlaceholderText("Click 'Toggle Inspect' then click elements on the page.")
        # We'll enable the inspect button later when scripts are ready
        self.inspect_button.setEnabled(False)
        self.element_info_display.setMinimumHeight(100)
        self.send_css_to_editor_btn = QtWidgets.QPushButton("Send CSS Selector to Editor")
        self.send_css_to_editor_btn.setEnabled(False) # Enable when selector exists
        inspector_layout.addWidget(self.inspect_button)
        inspector_layout.addWidget(self.element_info_display)
        inspector_layout.addWidget(self.send_css_to_editor_btn)
        helper_layout.addWidget(inspector_group)

        # Selector Tester
        selector_group = QtWidgets.QGroupBox("Selector Tester")
        selector_layout = QtWidgets.QFormLayout(selector_group)
        self.css_input = QtWidgets.QLineEdit()
        self.css_input.setPlaceholderText("e.g., div.product > h1::text")
        self.xpath_input = QtWidgets.QLineEdit()
        self.xpath_input.setPlaceholderText("e.g., //div[@class='product']/h1/text()")
        self.test_selector_button = QtWidgets.QPushButton("Test Static HTML") # Renamed
        self.test_selector_button.setToolTip("Test selectors against the initial HTML source (requires parsel or lxml)")
        self.test_selector_button.setEnabled(False) # Enabled when page loaded
        self.test_live_selector_button = QtWidgets.QPushButton("Test Live DOM") # New button
        self.test_live_selector_button.setToolTip("Test selectors against the current browser DOM (slower, reflects JS changes)")
        self.test_live_selector_button.setEnabled(False) # Enabled when page loaded

        # Add label for dependency warnings
        self.selector_dependency_label = QtWidgets.QLabel("")
        self.selector_dependency_label.setStyleSheet("color: orange;") # Warning color
        self.selector_dependency_label.setVisible(not self.selector_libs_ok)
        if not self.selector_libs_ok:
            self.selector_dependency_label.setText("Warning: 'parsel' or 'lxml' not found. Static testing disabled.")
            self.test_selector_button.setEnabled(False)
            self.test_selector_button.setToolTip("Disabled: Install 'parsel' or 'lxml' for static HTML testing.")


        self.selector_results_display = QtWidgets.QTextEdit()
        self.selector_results_display.setReadOnly(True)
        self.selector_results_display.setPlaceholderText("Results will appear here...")
        self.selector_results_display.setMinimumHeight(100)
        self.send_tested_css_btn = QtWidgets.QPushButton("Send CSS to Editor")
        self.send_tested_xpath_btn = QtWidgets.QPushButton("Send XPath to Editor")

        selector_layout.addRow("CSS:", self.css_input)
        selector_layout.addRow("XPath:", self.xpath_input)
        # Add both buttons in a horizontal layout for better spacing
        test_button_layout = QtWidgets.QHBoxLayout()
        test_button_layout.addWidget(self.test_selector_button)
        test_button_layout.addWidget(self.test_live_selector_button)
        selector_layout.addRow(test_button_layout) # Add the layout containing buttons
        # Removed duplicate addRow here
        selector_layout.addRow(self.selector_dependency_label) # Add warning label here
        selector_layout.addRow(QtWidgets.QLabel("Results:"))
        selector_layout.addRow(self.selector_results_display)
        selector_layout.addRow(self.send_tested_css_btn, self.send_tested_xpath_btn)
        helper_layout.addWidget(selector_group)

        # Source Viewer
        source_group = QtWidgets.QGroupBox("Page Source")
        source_layout = QtWidgets.QVBoxLayout(source_group) # Changed to VBox for label
        self.view_source_button = QtWidgets.QPushButton("View Rendered HTML")
        self.view_source_button.setToolTip("View the rendered HTML source (requires Pygments for syntax highlighting)")
        self.view_source_button.setEnabled(False) # Enabled when page loaded

        self.source_dependency_label = QtWidgets.QLabel("")
        self.source_dependency_label.setStyleSheet("color: orange;")
        self.source_dependency_label.setVisible(not self.pygments_ok)
        if not self.pygments_ok:
             self.source_dependency_label.setText("Info: Install 'Pygments' for syntax highlighting.")

        source_layout.addWidget(self.view_source_button)
        source_layout.addWidget(self.source_dependency_label) # Add label below button
        helper_layout.addWidget(source_group)

        helper_layout.addStretch() # Push tools upwards

        main_layout.addWidget(helper_panel, 3) # Helper takes 30% width


    def _setup_signals(self):
        # ... (Same signal connections) ...
        # Navigation
        self.back_action.triggered.connect(self.web_view.back)
        self.forward_action.triggered.connect(self.web_view.forward)
        self.reload_action.triggered.connect(self.web_view.reload)
        self.stop_action.triggered.connect(self.web_view.stop)
        self.url_input.returnPressed.connect(self.load_url)

        # Web View State Changes
        self.web_view.urlChanged.connect(self.update_url_bar)
        # Connect loadStarted to reset the JS initialized flag
        self.web_view.loadStarted.connect(self._page_load_started)
        self.web_view.loadProgress.connect(lambda p: self.set_status(f"Loading... {p}%"))
        self.web_view.loadFinished.connect(self.page_loaded) # page_loaded will now run all JS

        # Helper Tool Signals
        self.test_selector_button.clicked.connect(self.test_static_selectors)
        self.test_live_selector_button.clicked.connect(self.test_live_selectors)
        self.view_source_button.clicked.connect(self.view_rendered_source)
        self.inspect_button.toggled.connect(self.toggle_inspect_mode)
        self.send_css_to_editor_btn.clicked.connect(self.send_inspected_css_to_editor)
        self.send_tested_css_btn.clicked.connect(lambda: self.send_selector_to_editor('css'))
        self.send_tested_xpath_btn.clicked.connect(lambda: self.send_selector_to_editor('xpath'))

        # Connect the bridge signals to the handlers
        self.inspector_bridge.elementInfoReceived.connect(self.handle_inspector_result)
        self.inspector_bridge.liveSelectorResults.connect(self.handle_live_selector_results)
    @Slot()
    def _page_load_started(self):
        """Reset JS initialization flag when a new page starts loading."""
        self.js_initialized = False
        self.set_status("Loading page...")
        self.inspect_button.setEnabled(False) # Disable buttons during load
        self.test_selector_button.setEnabled(False)
        self.test_live_selector_button.setEnabled(False)
        self.view_source_button.setEnabled(False)
        if self.inspect_mode:
            self.inspect_button.setChecked(False) # Turn off inspect mode
    @Slot()
    def load_url(self):
        """Loads the URL from the input field."""
        url_text = self.url_input.text().strip()
        if not url_text:
            return
        # Basic check for scheme, default to http
        if not url_text.lower().startswith(('http://', 'https://', 'file://')):
            url_text = 'http://' + url_text

        url = QUrl.fromUserInput(url_text)
        if url.isValid():
            self.web_view.setUrl(url)
            self.set_status(f"Loading {url.toString()}...")
            # Clear previous results and disable buttons until loaded
            self.html_content = ""
            self.selector_results_display.clear()
            self.element_info_display.clear()
            self.send_css_to_editor_btn.setEnabled(False)
            self.test_selector_button.setEnabled(False)
            self.inspect_button.setEnabled(False)
            self.test_live_selector_button.setEnabled(False)
            self.view_source_button.setEnabled(False)
            # Disable inspect mode if active
            if self.inspect_mode:
                self.inspect_button.setChecked(False)
        else:
            self.set_status(f"Invalid URL: {url_text}")
            QMessageBox.warning(self, "Invalid URL", f"The entered URL is invalid:\n{url_text}")

    @Slot(QUrl)
    def update_url_bar(self, url):
        """Updates the URL bar when the page changes."""
        self.url_input.setText(url.toString())
        self.url_input.setCursorPosition(0)

    @Slot(bool)
    def page_loaded(self, ok):
        """Called when page load finishes. Runs all necessary JS."""
        if ok:
            self.set_status(f"Page loaded: {self.web_view.title()}")

            # --- Combine and run all JS initialization code ---
            full_js_init_code = f"""
                (function() {{
                    console.log('[page_loaded] Running combined JS initialization...');
                    let channelInitialized = false;
                    let inspectorDefined = false;

                    // 1. Define QWebChannel (if not already defined by previous script runs)
                    if (typeof QWebChannel === 'undefined') {{
                        {QWEBCHANNEL_JS_CODE}
                        console.log('[page_loaded] QWebChannel class defined.');
                    }} else {{
                        console.log('[page_loaded] QWebChannel class already defined.');
                    }}

                    // 2. Define Inspector Functions (if not already defined)
                    if (typeof window.startScrapyInspector === 'undefined') {{
                        try {{
                            {INSPECT_ELEMENT_JS_CODE}
                            inspectorDefined = true;
                            console.log('[page_loaded] Inspector functions defined.');
                        }} catch (inspectorError) {{
                            console.error('[page_loaded] Error executing INSPECT_ELEMENT_JS_CODE:', inspectorError);
                            inspectorDefined = false;
                        }}
                    }} else {{
                        inspectorDefined = true;
                        console.log('[page_loaded] Inspector functions already defined.');
                    }}

                    // 3. Attempt to initialize the WebChannel
                    if (typeof QWebChannel !== 'undefined' && (typeof qt !== 'undefined' && typeof qt.webChannelTransport !== 'undefined')) {{
                        try {{
                            console.log('[page_loaded] Attempting new QWebChannel connection...');
                            new QWebChannel(qt.webChannelTransport, function(channel) {{
                                window.inspectorBridge = channel.objects.inspectorBridge;
                                if (window.inspectorBridge) {{
                                    console.log("[page_loaded] SUCCESS: QWebChannel connected and window.inspectorBridge assigned.");
                                    channelInitialized = true;
                                }} else {{
                                    console.error("[page_loaded] FAILURE: QWebChannel connected but channel.objects.inspectorBridge was not found.");
                                    channelInitialized = false;
                                }}
                                // Python callback doesn't directly see this, relies on bridge working
                            }});
                        }} catch (e) {{
                            console.error('[page_loaded] Error during new QWebChannel():', e);
                            channelInitialized = false;
                        }}
                    }} else {{
                        console.error('[page_loaded] Cannot init channel: QWebChannel class or qt.webChannelTransport missing.');
                        channelInitialized = false;
                    }}

                    // Return overall success based on both parts
                    return {{ channel: channelInitialized, inspector: inspectorDefined }};
                }})();
            """

            self.page.runJavaScript(full_js_init_code, QWebEngineScript.ScriptWorldId.ApplicationWorld,
                                  self._handle_full_js_init_result) # Use a new callback

            self.page.toHtml(self._html_fetched_callback) # Request HTML
        else:
            # Handle load errors (same as before)
            # ... (error handling code, ensure buttons are disabled) ...
            self.inspect_button.setEnabled(False)
            self.inspect_button.setChecked(False)
            self.test_selector_button.setEnabled(False)
            self.test_live_selector_button.setEnabled(False)
            self.view_source_button.setEnabled(False)

    def _handle_full_js_init_result(self, result):
        """Handles the result of the combined JavaScript initialization."""
        if isinstance(result, dict):
            self.js_initialized = result.get('channel', False) and result.get('inspector', False)
            channel_ok = result.get('channel', False)
            inspector_ok = result.get('inspector', False)
            logger.info(f"Combined JS init result: Channel OK={channel_ok}, Inspector OK={inspector_ok}")
            if self.js_initialized:
                self.inspect_button.setEnabled(True) # Enable button only if everything succeeded
                self.set_status("Browser helper ready.", 3000)
            else:
                self.inspect_button.setEnabled(False)
                error_msg = "Error initializing browser helper:"
                if not channel_ok: error_msg += " Channel connection failed."
                if not inspector_ok: error_msg += " Inspector functions failed."
                self.set_status(error_msg, 5000)
                logger.error(error_msg + " Check DevTools console for details.")
        else:
            # Fallback if result isn't the expected dictionary
            self.js_initialized = False
            self.inspect_button.setEnabled(False)
            logger.error(f"Unexpected result from combined JS init: {result}")
            self.set_status("Error initializing browser helper (unexpected result).", 5000)
    @Slot(str)
    def _html_fetched_callback(self, html):
        """Callback triggered when toHtml() finishes."""
        self.html_content = html
        # Enable buttons based on page load AND dependencies
        self.test_selector_button.setEnabled(self.html_content != "" and self.selector_libs_ok)
        self.test_live_selector_button.setEnabled(self.html_content != "")
        self.view_source_button.setEnabled(self.html_content != "")
        logger.debug(f"Fetched HTML content ({len(html)} bytes)")

    def toggle_inspect_mode(self, checked):
        """Enables or disables the JavaScript-based element inspector."""
        # Only proceed if JS initialization was successful for this page load
        if not self.js_initialized:
            logger.warning("Cannot toggle inspect: Core JS not initialized for this page.")
            self.inspect_button.setChecked(False) # Prevent toggle if not ready
            QMessageBox.warning(self, "Initialization Error", "Browser helper scripts did not initialize correctly. Please reload the page.")
            return

        self.inspect_mode = checked
        if not self.page:
             logger.warning("Inspect toggle attempted but page object is not available.")
             self.inspect_button.setChecked(False)
             return

        function_name = "startScrapyInspector" if checked else "stopScrapyInspector"
        js_code = f"""
            if (typeof window.{function_name} === 'function') {{
                window.{function_name}();
                console.log('[toggle_inspect_mode] {function_name} called.');
            }} else {{
                console.error('[toggle_inspect_mode] {function_name} function is not defined. This should not happen if js_initialized is true.');
                // Alert Python side about the inconsistency
                if(window.inspectorBridge && window.inspectorBridge.logError) {{
                    window.inspectorBridge.logError('{function_name} is unexpectedly not defined.');
                }}
            }}
        """
        self.page.runJavaScript(js_code, QWebEngineScript.ScriptWorldId.ApplicationWorld)
        logger.debug(f"Attempted to call JS function: {function_name}")
        status_msg = "Inspect mode enabled. Click elements on the page." if checked else "Inspect mode disabled."
        self.set_status(status_msg)

        if not checked:
            self.inspected_css_selector = None
            self.send_css_to_editor_btn.setEnabled(False)
    @Slot(bool)
    def page_loaded(self, ok):
        """Called when page load finishes. Tries to init JS channel."""
        self.inspect_button.setEnabled(ok) # Enable inspect button only if page load succeeded

        if ok:
            self.set_status(f"Page loaded: {self.web_view.title()}")

            # --- Attempt to initialize the JS-side QWebChannel ---
            js_init_channel = """
                (function() {
                    console.log('[page_loaded] Attempting JS channel initialization...');
                    if (typeof QWebChannel === 'undefined') {
                        console.error('[page_loaded] QWebChannel class is not defined. qwebchannel.js might not have loaded.');
                        return false; // Indicate failure
                    }
                    if (typeof qt === 'undefined' || typeof qt.webChannelTransport === 'undefined') {
                        console.error('[page_loaded] qt.webChannelTransport is not defined. Bridge injection failed or happened too late.');
                        return false; // Indicate failure
                    }

                    try {
                        console.log('[page_loaded] Prerequisites met. Creating QWebChannel instance...');
                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            window.inspectorBridge = channel.objects.inspectorBridge;
                            if (window.inspectorBridge) {
                                console.log("[page_loaded] SUCCESS: QWebChannel connected and window.inspectorBridge assigned.");
                            } else {
                                console.error("[page_loaded] FAILURE: QWebChannel connected but channel.objects.inspectorBridge was not found. Check Python registration.");
                            }
                        });
                        return true; // Indicate potential success (async callback will confirm)
                    } catch (e) {
                        console.error('[page_loaded] Error during new QWebChannel():', e);
                        return false; // Indicate failure
                    }
                })();
            """
            self.page.runJavaScript(js_init_channel, QWebEngineScript.ScriptWorldId.ApplicationWorld,
                                  self._handle_channel_init_result) # Use a callback

            self.page.toHtml(self._html_fetched_callback)
        else:
            # Handle load errors (same as before)
            error_string = self.page.property("errorString")
            if not error_string:
                if self.web_view.url().isEmpty() or self.web_view.url().toString() == "about:blank":
                     error_string = "Load cancelled or failed"
                else:
                     error_string = "Unknown error"
            self.set_status(f"Failed to load page: {error_string}")
            self.html_content = ""
            self.inspect_button.setChecked(False)
            self.test_selector_button.setEnabled(False)
            self.test_live_selector_button.setEnabled(False)
            self.view_source_button.setEnabled(False)
            self.selector_results_display.clear()
            self.element_info_display.clear()

    # --- NEW Callback for JS Initialization Attempt ---

    def _handle_channel_init_result(self, result):
            """Handles the result of the JavaScript trying to initialize the channel."""
            if result is True:
                logger.info("JavaScript reported successful initiation of QWebChannel connection attempt.")
                # We now rely on the JS callback within new QWebChannel to assign inspectorBridge
            elif result is False:
                logger.error("JavaScript reported failure during QWebChannel initialization attempt (likely missing QWebChannel class or qt.webChannelTransport). Bridge may not work.")
                # Don't disable the button here, maybe it connects later on interaction?
                # But log the warning.
                self.set_status("Warning: Browser helper bridge failed initial connection.", 5000)
            else:
                logger.warning(f"Unexpected result from JS channel initialization: {result}")
            
    

    @Slot()
    def test_static_selectors(self):
        """Runs CSS and XPath selectors against the fetched static HTML."""
        if not self.html_content:
            QMessageBox.warning(self, "No Static HTML", "Static page HTML not loaded yet or failed to load. Please wait or reload.")
            return
        if not USE_PARSEL and not 'lxml_html' in globals():
             QMessageBox.critical(self, "Missing Library", "Selector testing requires 'parsel' or 'lxml'. Please install one.")
             return

        css_selector = self.css_input.text().strip()
        xpath_selector = self.xpath_input.text().strip()

        if not css_selector and not xpath_selector:
            self.selector_results_display.setText("Please enter a CSS or XPath selector to test against static HTML.")
            return

        self.selector_results_display.setText("Testing selectors against static HTML...")
        # Use QApplication.processEvents() to ensure the UI updates before potentially long parsing
        QApplication.processEvents()

        results = []
        try:
            if USE_PARSEL:
                sel = Selector(text=self.html_content)
                if css_selector:
                    results.append(f"--- CSS Results ({css_selector}) ---")
                    try:
                        css_results = sel.css(css_selector).getall()
                        results.append(f"Found {len(css_results)} element(s):")
                        results.extend([r.strip() for r in css_results][:20]) # Limit results shown
                        if len(css_results) > 20: results.append("... (results truncated)")
                    except Exception as e_css: # Catch errors during selection
                        results.append(f"Static CSS Error: {e_css}")

                if xpath_selector:
                    results.append(f"\n--- Static XPath Results ({xpath_selector}) ---")
                    try:
                        xpath_results = sel.xpath(xpath_selector).getall()
                        results.append(f"Found {len(xpath_results)} element(s):")
                        results.extend([r.strip() for r in xpath_results][:20])
                        if len(xpath_results) > 20: results.append("... (results truncated)")
                    except Exception as e_xpath: # Catch errors during selection
                        results.append(f"Static XPath Error: {e_xpath}")

            elif 'lxml_html' in globals(): # Fallback to lxml if parsel not installed but lxml is
                tree = lxml_html.fromstring(self.html_content.encode('utf-8')) # lxml needs bytes
                if css_selector:
                    results.append(f"--- CSS Results ({css_selector}) ---")
                    try:
                        # Requires cssselect package: pip install cssselect
                        import cssselect
                        css_results_nodes = tree.cssselect(css_selector)
                        css_results = [lxml_html.tostring(node, encoding='unicode', pretty_print=True).strip() for node in css_results_nodes]
                        results.append(f"Found {len(css_results)} element(s):")
                        results.extend(css_results[:20])
                        if len(css_results) > 20: results.append("... (results truncated)")
                    except ImportError:
                        results.append("LXML CSS selectors require 'cssselect'. Please install it.")
                    except cssselect.SelectorError as e:
                        results.append(f"Static CSS Selector Error: {e}")
                    except Exception as e_css:
                         results.append(f"Static CSS Error: {e_css}")

                if xpath_selector:
                    results.append(f"\n--- Static XPath Results ({xpath_selector}) ---")
                    try:
                        xpath_results_nodes = tree.xpath(xpath_selector)
                        # Handle text nodes and elements differently
                        xpath_results = []
                        for node in xpath_results_nodes:
                            if isinstance(node, str):
                                xpath_results.append(node.strip())
                            else: # Assuming it's an element node
                                xpath_results.append(lxml_html.tostring(node, encoding='unicode', pretty_print=True).strip())

                        results.append(f"Found {len(xpath_results)} element(s):")
                        results.extend(xpath_results[:20])
                        if len(xpath_results) > 20: results.append("... (results truncated)")
                    except lxml_html.etree.XPathEvalError as e:
                        results.append(f"Static XPath Error: {e}")
                    except Exception as e_xpath:
                         results.append(f"Static XPath Error: {e_xpath}")

            self.selector_results_display.setText("\n".join(results))

        except Exception as e:
            logger.exception("Error testing static selectors:")
            self.selector_results_display.setText(f"Static Test Error: {e}")

    @Slot()
    def test_live_selectors(self):
        """Triggers CSS and XPath selector tests against the live browser DOM."""
        if not self.page:
            QMessageBox.warning(self, "No Page", "Browser page not available for live testing.")
            return

        css_selector = self.css_input.text().strip()
        xpath_selector = self.xpath_input.text().strip()

        if not css_selector and not xpath_selector:
            self.selector_results_display.setText("Please enter a CSS or XPath selector to test against the live DOM.")
            return

        self.selector_results_display.setText("Testing selectors against live DOM...")
        QApplication.processEvents()

        # Generate unique request IDs
        css_request_id = -1
        xpath_request_id = -1

        # Clear previous results for live tests
        live_results = []

        if css_selector:
            css_request_id = self._get_next_request_id()
            self.live_test_requests[css_request_id] = "css" # Store type for result handling
            live_results.append(f"--- Live CSS Results ({css_selector}) [Requesting...] ---")
            js_code = f"window.testSelectorLive('{self._escape_js_string(css_selector)}', 'css', {css_request_id});"
            self.page.runJavaScript(js_code)
            logger.debug(f"Sent live CSS test request {css_request_id}")

        if xpath_selector:
            xpath_request_id = self._get_next_request_id()
            self.live_test_requests[xpath_request_id] = "xpath"
            live_results.append(f"\n--- Live XPath Results ({xpath_selector}) [Requesting...] ---")
            js_code = f"window.testSelectorLive('{self._escape_js_string(xpath_selector)}', 'xpath', {xpath_request_id});"
            self.page.runJavaScript(js_code)
            logger.debug(f"Sent live XPath test request {xpath_request_id}")

        # Update display immediately to show "Requesting..."
        self.selector_results_display.setText("\n".join(live_results))

    def _get_next_request_id(self):
        """Generates a unique ID for live test requests."""
        # Simple counter, could be made more robust if needed
        current_id = getattr(self, "_live_test_counter", 0) + 1
        self._live_test_counter = current_id
        return current_id

    def _escape_js_string(self, value):
        """Escapes a string for safe insertion into JavaScript code."""
        # Basic escaping, might need refinement for complex cases
        return value.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '')

    @Slot(int, str, str)
    def handle_live_selector_results(self, request_id, json_results, error_string):
        """Receives and displays results from live DOM selector tests."""
        logger.debug(f"Received live results for request {request_id}. Error: {error_string}")
        if request_id not in self.live_test_requests:
            logger.warning(f"Received live results for unknown request ID: {request_id}")
            return

        selector_type = self.live_test_requests.pop(request_id) # Get type and remove from pending
        current_text = self.selector_results_display.toPlainText()
        results_placeholder = f"--- Live {selector_type.upper()} Results (.*?) \\[Requesting...\\] ---"
        new_results_text = ""

        if error_string:
            new_results_text = f"--- Live {selector_type.upper()} Results --- \nError: {error_string}"
        else:
            try:
                results_list = json.loads(json_results)
                count = len(results_list)
                new_results_text = f"--- Live {selector_type.upper()} Results --- \nFound {count} element(s):\n"
                new_results_text += "\n".join(results_list[:20]) # Limit results
                if count > 20:
                    new_results_text += "\n... (results truncated)"
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode live results JSON for request {request_id}: {e}")
                new_results_text = f"--- Live {selector_type.upper()} Results --- \nError: Failed to parse results from browser."
            except Exception as e:
                 logger.error(f"Error processing live results for request {request_id}: {e}")
                 new_results_text = f"--- Live {selector_type.upper()} Results --- \nError: {e}"

        # Replace the placeholder in the text edit
        # Use regex to replace the correct placeholder section
        import re
        updated_text = re.sub(results_placeholder, new_results_text.replace('\\', r'\\'), current_text, flags=re.DOTALL)

        if updated_text == current_text:
             # Placeholder not found, maybe it was cleared? Append instead.
             logger.warning(f"Placeholder for request {request_id} not found, appending results.")
             current_text += "\n" + new_results_text
             updated_text = current_text

        self.selector_results_display.setText(updated_text)
        QApplication.processEvents() # Ensure UI updates

    @Slot()
    def view_rendered_source(self):
        """Shows the rendered HTML source in a dialog."""
        if not self.html_content:
            QMessageBox.warning(self, "No HTML", "Page HTML not available.")
            return

        dialog = HtmlViewDialog(self.html_content, self)
        dialog.exec() # Use exec() for modal dialog

    @Slot(dict)
    def handle_inspector_result(self, info):
         """Handles the element info received via QWebChannel."""
         if not self.inspect_mode:
             logger.warning("Received inspector result while inspect mode is off. Ignoring.")
             return

         try:
            logger.debug(f"Received inspector result via QWebChannel: {info}")
            display_text = (
                f"Tag: {info.get('tag', 'N/A')}\n"
                f"ID: {info.get('id', 'None')}\n"
                f"Classes: {info.get('classes', 'None')}\n"
                f"Attributes: {json.dumps(info.get('attributes', {}), indent=1)}\n"
                f"Text (preview): {info.get('text', '')}\n"
                f"Simple CSS: {info.get('css_selector', 'N/A')}"
            )
            self.element_info_display.setText(display_text)
            self.inspected_css_selector = info.get('css_selector') # Store for sending
            self.send_css_to_editor_btn.setEnabled(bool(self.inspected_css_selector))
            self.set_status("Element info captured.")

         except Exception as e:
            logger.error(f"Error processing inspector result from channel: {e}")
            self.element_info_display.setText(f"Error processing result: {e}")
            self.send_css_to_editor_btn.setEnabled(False)

    @Slot()
    def send_inspected_css_to_editor(self):
        """Sends the CSS selector from the inspector to the editor."""
        if self.inspected_css_selector:
             # Add ::text or ::attr(href) common examples
            snippet = f"response.css('{self.inspected_css_selector}')"
            menu = QtWidgets.QMenu(self)
            menu.addAction(f"Send: {snippet}.get()").triggered.connect(lambda: self._send_text_to_editor(snippet + ".get()"))
            menu.addAction(f"Send: {snippet}.getall()").triggered.connect(lambda: self._send_text_to_editor(snippet + ".getall()"))
            menu.addAction(f"Send: {snippet}::text.get()").triggered.connect(lambda: self._send_text_to_editor(snippet + "::text.get()"))
            menu.addAction(f"Send: {snippet}::attr(href).get()").triggered.connect(lambda: self._send_text_to_editor(snippet + "::attr(href).get()"))
            menu.exec(self.send_css_to_editor_btn.mapToGlobal(self.send_css_to_editor_btn.rect().bottomLeft()))

        else:
            logger.warning("No inspected CSS selector available to send.")

    @Slot(str)
    def send_selector_to_editor(self, selector_type):
        """Sends the currently entered CSS or XPath selector to the editor with options."""
        selector = ""
        method = ""
        if selector_type == 'css':
            selector = self.css_input.text().strip()
            method = "css"
        elif selector_type == 'xpath':
            selector = self.xpath_input.text().strip()
            method = "xpath"

        if selector:
            snippet_base = f"response.{method}('{selector}')"
            button = self.send_tested_css_btn if selector_type == 'css' else self.send_tested_xpath_btn

            menu = QtWidgets.QMenu(self)
            menu.addAction(f"Send: {snippet_base}.get()").triggered.connect(lambda: self._send_text_to_editor(snippet_base + ".get()"))
            menu.addAction(f"Send: {snippet_base}.getall()").triggered.connect(lambda: self._send_text_to_editor(snippet_base + ".getall()"))
            menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

        else:
            logger.warning(f"No {selector_type} selector entered to send.")

    def _send_text_to_editor(self, text):
        """Helper to send text to the main window's code editor."""
        if not hasattr(self.main_window, 'code_editor'):
            logger.error("Main window does not have 'code_editor' attribute.")
            QMessageBox.critical(self, "Error", "Cannot find code editor.")
            return

        editor = self.main_window.code_editor
        editor_tab = getattr(self.main_window, 'editor_tab', None) # Use getattr for safety
        tab_widget = getattr(self.main_window, 'tab_widget', None)

        # Switch to editor tab
        if editor_tab and tab_widget:
            try:
                tab_widget.setCurrentWidget(editor_tab)
            except Exception as e:
                logger.warning(f"Could not switch to editor tab: {e}")

        # Insert text ensuring editor is focused and writable
        if editor.isEnabled() and not editor.isReadOnly():
             editor.setFocus() # Set focus before inserting
             cursor = editor.textCursor()
             cursor.insertText(text + "\n") # Add newline for better formatting
             logger.info(f"Sent to editor: {text}")
        else:
             logger.warning("Editor not enabled or is read-only. Cannot insert text.")
             QMessageBox.warning(self, "Editor Not Ready", "The code editor is not currently active or writable.")

    def set_status(self, message, timeout=3000):
        """Updates the main window status bar."""
        if self.main_window and hasattr(self.main_window, 'statusBar'):
            # Ensure this runs on the main thread if called from elsewhere
            QtCore.QMetaObject.invokeMethod(self.main_window.statusBar(), "showMessage",
                                           Qt.QueuedConnection,
                                           QtCore.Q_ARG(str, message),
                                           QtCore.Q_ARG(int, timeout))

class Plugin(PluginBase):
    """
    Plugin to add a Scrapy Helper Browser tab.
    """
    def __init__(self):
        super().__init__()
        self.name = "Scrapy Helper Browser"
        self.description = "Adds a browser tab with tools for inspecting pages and testing selectors."
        self.version = "1.2.0"
        self.main_window = None
        self.browser_tab = None

    def initialize_ui(self, main_window):
        """Create the Browser tab and add it to the main window."""
        self.main_window = main_window

        if hasattr(main_window, 'tab_widget'):
            try:
                self.browser_tab = ScrapyBrowserTab(main_window)
                # Attempt to add with an icon from Qt's standard themes
                icon = QIcon.fromTheme("web-browser", QIcon()) # Provide empty fallback
                main_window.tab_widget.addTab(self.browser_tab, icon, "Helper Browser")
                logger.info("Scrapy Helper Browser plugin initialized UI.")
            except Exception as e:
                 logger.exception("Failed to initialize Scrapy Helper Browser UI:")
                 QMessageBox.critical(main_window, "Plugin Error", f"Failed to initialize Scrapy Helper Browser:\n{e}")

        else:
            logger.error("Could not find main window's tab_widget to add Browser tab.")

    def on_app_exit(self):
        """Clean up resources if necessary."""
        # QWebEngineView should manage its process, but explicit cleanup can be added if needed
        if self.browser_tab and hasattr(self.browser_tab, 'web_view'):
             self.browser_tab.web_view.stop() # Stop loading
        logger.info("Scrapy Helper Browser plugin exiting.")