/**
 * inspector.js - Element inspection script for Scrapy Helper Browser
 *
 * This script should be saved to: /plugins/resources/inspector.js
 */

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