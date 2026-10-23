/**
 * Helpers for rendering untrusted HTML (Linsight deliverables, uploaded files)
 * inside a sandboxed iframe.
 *
 * The sandbox deliberately omits `allow-same-origin`: with `srcDoc`, an
 * about:srcdoc document inherits the embedder's origin, so granting it would let
 * a generated page read the app's localStorage/cookies and reach into
 * `parent.document` — turning every deliverable into an XSS vector. The cost of
 * withholding it is an opaque origin, where reading `localStorage` /
 * `sessionStorage` throws:
 *
 *   SecurityError: Failed to read the 'localStorage' property from 'Window':
 *   The document is sandboxed and lacks the 'allow-same-origin' flag.
 *
 * That throw is fatal, not cosmetic. A generated HTML deck typically touches
 * storage at the top level of its main script (remembering slide position, theme
 * or speaker-note preferences); the exception aborts the whole <script> block, so
 * every listener registered after that line — keydown, wheel, touch — is never
 * bound and the page renders but cannot be operated. Downloading the same file
 * and opening it over file:// works because file:// has a real origin.
 *
 * `buildSandboxedSrcDoc` therefore prepends an in-memory storage shim so the
 * page's own scripts run to completion. Preferences do not persist across
 * reloads, which is an acceptable trade for keeping the origin boundary intact.
 */

/**
 * Feature tokens granted to the artifact frame. `allow-same-origin` is excluded
 * on purpose (see above). `allow-popups-to-escape-sandbox` is excluded too: it
 * would let a generated page open an unsandboxed window at any URL.
 */
export const ARTIFACT_SANDBOX =
    'allow-scripts allow-popups allow-modals allow-downloads allow-forms';

/**
 * In-memory stand-ins for the two Web Storage areas, installed only when the
 * real ones are unreachable. `localStorage` is an accessor on `Window.prototype`,
 * so an own property defined on `window` shadows it.
 */
const STORAGE_SHIM = `<script>(function () {
  try { window.localStorage.getItem('__bs_probe__'); return; } catch (e) {}
  function makeStorage() {
    var data = Object.create(null);
    return {
      getItem: function (k) { k = String(k); return k in data ? data[k] : null; },
      setItem: function (k, v) { data[String(k)] = String(v); },
      removeItem: function (k) { delete data[String(k)]; },
      clear: function () { data = Object.create(null); },
      key: function (i) { var keys = Object.keys(data); return i < keys.length ? keys[i] : null; },
      get length() { return Object.keys(data).length; }
    };
  }
  ['localStorage', 'sessionStorage'].forEach(function (name) {
    try {
      Object.defineProperty(window, name, { value: makeStorage(), configurable: true });
    } catch (e) {}
  });
})();</script>`;

/**
 * Insert the shim at the earliest position that keeps the document in standards
 * mode — anything placed before the doctype would trigger quirks mode and break
 * the page's layout, which is a worse regression than the one we are fixing.
 */
export function buildSandboxedSrcDoc(html: string): string {
    if (!html) return html;

    const after = (match: RegExpMatchArray | null): string | null => {
        if (!match || match.index === undefined) return null;
        const at = match.index + match[0].length;
        return html.slice(0, at) + STORAGE_SHIM + html.slice(at);
    };

    return (
        after(html.match(/<head\b[^>]*>/i)) ??
        after(html.match(/<html\b[^>]*>/i)) ??
        after(html.match(/<!doctype\s+html[^>]*>/i)) ??
        STORAGE_SHIM + html
    );
}

/**
 * Keyboard-driven pages (decks, viewers) bind their listeners on the iframe's own
 * window, which never sees a key event until the frame holds focus. The artifact
 * fills the whole view, so focusing it on load is what the user expects — without
 * this they must click inside before the arrow keys do anything.
 */
export function focusArtifactFrame(frame: HTMLIFrameElement | null): void {
    frame?.focus();
}
