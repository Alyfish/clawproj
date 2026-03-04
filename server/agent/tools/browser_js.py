"""
Shared JavaScript constants for browser automation.

These JS snippets are evaluated in the browser via Playwright's
page.evaluate(). They're in a separate module to avoid circular
imports between browser_cdp.py and login_flow.py.
"""

# ── DOM Walker (Snapshot) ─────────────────────────────────────
# Exact copy from browser/src/snapshot.ts lines 39-306.
# Walks the DOM, produces [N] element "text" format, stores refs
# on window.__clawbot_refs with {selector, tagName, description, rect}.

DOM_WALKER_JS = """(function buildSnapshot() {
  var MAX_SNAPSHOT_CHARS = 6000;
  var MAX_OPTIONS = 10;
  var MAX_HREF_CHARS = 80;
  var MAX_TEXT_CHARS = 60;
  var PAGE_TEXT_CHARS = 2000;

  var INTERACTIVE_SELECTORS = [
    'a[href]', 'button', 'input', 'select', 'textarea',
    '[role="button"]', '[role="link"]', '[role="checkbox"]',
    '[role="tab"]', '[role="menuitem"]', '[role="switch"]',
    '[onclick]'
  ];

  var refs = {};
  var refCounter = 0;

  // --- Visibility check ---
  function isVisible(el) {
    try {
      if (el.getAttribute('aria-hidden') === 'true') return false;
      var style = window.getComputedStyle(el);
      if (style.display === 'none') return false;
      if (style.visibility === 'hidden') return false;
      if (parseFloat(style.opacity) === 0) return false;
      var rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      if (rect.bottom < -100 || rect.top > window.innerHeight * 2) return false;
      if (rect.right < -100 || rect.left > window.innerWidth * 2) return false;
      return true;
    } catch (e) {
      return false;
    }
  }

  // --- Check if element is inside a hidden ancestor ---
  function hasHiddenAncestor(el) {
    var node = el.parentElement;
    while (node && node !== document.body) {
      try {
        var style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return true;
        if (node.getAttribute('aria-hidden') === 'true') return true;
      } catch (e) {
        return false;
      }
      node = node.parentElement;
    }
    return false;
  }

  // --- Unique selector generator ---
  function getSelector(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    var parts = [];
    var node = el;
    while (node && node !== document.body && node !== document.documentElement) {
      var seg = node.tagName.toLowerCase();
      if (node.id) {
        parts.unshift('#' + CSS.escape(node.id));
        break;
      }
      var parent = node.parentElement;
      if (parent) {
        var siblings = Array.from(parent.children).filter(function(c) {
          return c.tagName === node.tagName;
        });
        if (siblings.length > 1) {
          var idx = siblings.indexOf(node) + 1;
          seg += ':nth-of-type(' + idx + ')';
        }
      }
      parts.unshift(seg);
      node = node.parentElement;
    }
    return parts.join(' > ') || el.tagName.toLowerCase();
  }

  // --- Get label for an input/textarea ---
  function getLabel(el) {
    // 1. aria-label
    var aria = el.getAttribute('aria-label');
    if (aria) return aria;
    // 2. aria-labelledby
    var labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      var labelEl = document.getElementById(labelledBy);
      if (labelEl) return (labelEl.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
    }
    // 3. Associated <label>
    if (el.id) {
      var label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (label) return (label.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
    }
    // 4. Wrapping <label>
    var parentLabel = el.closest('label');
    if (parentLabel) {
      var text = (parentLabel.textContent || '').trim();
      if (text.length > 0) return text.substring(0, MAX_TEXT_CHARS);
    }
    // 5. placeholder
    if (el.placeholder) return el.placeholder;
    // 6. name attribute
    if (el.name) return el.name;
    return '';
  }

  // --- Escape quotes in strings ---
  function esc(s) {
    return (s || '').replace(/"/g, '\\\\"');
  }

  // --- Gather candidates ---
  var selectorStr = INTERACTIVE_SELECTORS.join(', ');
  var candidateSet = new Set();
  var rawCandidates = document.querySelectorAll(selectorStr);
  for (var i = 0; i < rawCandidates.length; i++) {
    candidateSet.add(rawCandidates[i]);
  }

  // Also find cursor:pointer elements not already matched
  var allDivLike = document.querySelectorAll('div, span, li, article, section, td, tr');
  for (var i = 0; i < allDivLike.length; i++) {
    var el = allDivLike[i];
    try {
      if (window.getComputedStyle(el).cursor === 'pointer' && !candidateSet.has(el)) {
        candidateSet.add(el);
      }
    } catch (e) {}
  }

  var candidates = Array.from(candidateSet);

  // Filter visible + no hidden ancestor
  candidates = candidates.filter(function(el) {
    return isVisible(el) && !hasHiddenAncestor(el);
  });

  // Sort by document position (DOM order)
  candidates.sort(function(a, b) {
    var pos = a.compareDocumentPosition(b);
    if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
    if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
    return 0;
  });

  // --- Build snapshot lines ---
  var lines = [];
  var title = document.title || '(untitled)';
  var url = window.location.href;
  lines.push('[Page] ' + title);
  lines.push('[URL] ' + url);
  lines.push('');

  for (var c = 0; c < candidates.length; c++) {
    var el = candidates[c];
    refCounter++;
    var ref = String(refCounter);
    var tag = el.tagName.toLowerCase();
    var rect = el.getBoundingClientRect();
    var selector = getSelector(el);
    var aria = el.getAttribute('aria-label') || '';
    var description = '';
    var line = '[' + ref + '] ';

    if (tag === 'input') {
      var type = (el.type || 'text').toLowerCase();
      var label = getLabel(el);
      var val = el.value || '';
      line += 'input';
      if (type !== 'text') line += '[' + type + ']';
      line += ' "' + esc(label) + '"';
      if (val) line += ' value="' + esc(val) + '"';
      description = 'input ' + label;
    } else if (tag === 'select') {
      var label = getLabel(el);
      var selected = (el.options && el.options[el.selectedIndex])
        ? el.options[el.selectedIndex].text : '';
      var opts = [];
      var optCount = el.options ? el.options.length : 0;
      for (var oi = 0; oi < Math.min(optCount, MAX_OPTIONS); oi++) {
        opts.push('"' + esc(el.options[oi].text) + '"');
      }
      line += 'select "' + esc(label) + '" value="' + esc(selected) + '"';
      line += ' options=[' + opts.join(',') + ']';
      if (optCount > MAX_OPTIONS) line += ' +' + (optCount - MAX_OPTIONS) + ' more';
      description = 'select ' + label;
    } else if (tag === 'textarea') {
      var label = getLabel(el);
      var val = (el.value || '').substring(0, 100);
      line += 'textarea "' + esc(label) + '"';
      if (val) line += ' value="' + esc(val) + '"';
      description = 'textarea ' + label;
    } else if (tag === 'a') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      var href = (el.getAttribute('href') || '').substring(0, MAX_HREF_CHARS);
      line += 'link "' + esc(text) + '"';
      if (aria && aria !== text) line += ' aria="' + esc(aria) + '"';
      line += ' -> ' + href;
      description = 'link ' + text;
    } else if (tag === 'button' || el.getAttribute('role') === 'button') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      line += 'button "' + esc(text) + '"';
      if (aria && aria !== text) line += ' aria="' + esc(aria) + '"';
      description = 'button ' + text;
    } else if (el.getAttribute('role') === 'checkbox') {
      var label = aria || (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      var checked = el.getAttribute('aria-checked') === 'true' || el.checked;
      line += 'checkbox "' + esc(label) + '"';
      if (checked) line += ' [checked]';
      description = 'checkbox ' + label;
    } else if (el.getAttribute('role') === 'tab') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      var selected = el.getAttribute('aria-selected') === 'true';
      line += 'tab "' + esc(text) + '"';
      if (selected) line += ' [selected]';
      description = 'tab ' + text;
    } else if (el.getAttribute('role') === 'link') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      line += 'link "' + esc(text) + '"';
      if (aria && aria !== text) line += ' aria="' + esc(aria) + '"';
      description = 'link ' + text;
    } else {
      // Generic clickable element (div, span, etc.)
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      line += tag + ' "' + esc(text) + '"';
      if (aria) line += ' aria="' + esc(aria) + '"';
      description = tag + ' ' + text;
    }

    refs[ref] = {
      selector: selector,
      tagName: tag,
      description: description,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
    };

    lines.push(line);

    // Check total size — leave room for page text section
    var currentLength = lines.join('\\n').length;
    if (currentLength > MAX_SNAPSHOT_CHARS - PAGE_TEXT_CHARS - 200) {
      var remaining = candidates.length - refCounter;
      if (remaining > 0) {
        lines.push('... [' + remaining + ' more interactive elements]');
      }
      break;
    }
  }

  // --- Page text section (above fold) ---
  lines.push('');
  lines.push('--- Page Text (above fold) ---');
  var bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
  var pageText = bodyText.substring(0, PAGE_TEXT_CHARS).replace(/\\n{3,}/g, '\\n\\n').trim();
  lines.push(pageText);

  // --- Store refs globally ---
  window.__clawbot_refs = refs;

  // --- Final truncation ---
  var snapshot = lines.join('\\n');
  if (snapshot.length > MAX_SNAPSHOT_CHARS) {
    snapshot = snapshot.substring(0, MAX_SNAPSHOT_CHARS) + '\\n... [snapshot truncated]';
  }

  return { snapshot: snapshot, elementCount: refCounter };
})()"""

# ── Ref Lookup ────────────────────────────────────────────────
# Same pattern as snapshot.ts:350-356

JS_LOOKUP_REF = """(ref) => {
    const refs = window.__clawbot_refs;
    if (!refs) return null;
    return refs[String(ref)] || null;
}"""

# ── Auth Indicator Detection ──────────────────────────────────
# Checks for common post-login UI elements (logout links, avatars, etc.)

JS_CHECK_AUTH_INDICATORS = """() => {
    try {
        const indicators = [
            'a[href*="logout"]', 'a[href*="signout"]', 'a[href*="sign-out"]',
            'a[href*="sign_out"]', 'button[aria-label*="Account"]',
            'button[aria-label*="account"]', '[data-testid*="avatar"]',
            'img[alt*="profile" i]', 'img[alt*="avatar" i]',
            '[aria-label*="Sign out"]', '[aria-label*="Log out"]',
        ];
        return !!document.querySelector(indicators.join(', '));
    } catch { return false; }
}"""
