/**
 * COFCO-only page display scale ("font size") preference.
 *
 * Levels map to a whole-page CSS zoom (small 90% / standard 100% / large 110%),
 * mirroring the browser's Cmd +/- effect without touching the browser zoom.
 * The preference lives in localStorage under a key shared with the workspace
 * client app (both apps are served from the same origin behind nginx).
 *
 * The zoom itself is applied to <body> by the CSS in style/index.css. Because
 * viewport units are NOT rescaled by zoom (measured in Chrome 150: under
 * `zoom: 1.1` a `100vh` box renders at 110% of the window), the body is sized
 * to the *reverse-compensated* viewport so that size x zoom lands back on the
 * physical window. The same compensation has to reach every hardcoded viewport
 * length in the app, which is what the --bs-vh / --bs-dvh / --bs-vw variables
 * below are for: call sites read them as `var(--bs-vh, 100vh)`, so the standard
 * level (no variables defined) behaves exactly like it does today.
 */
export type FontSizeLevel = 'small' | 'standard' | 'large';

export const FONT_SIZE_STORAGE_KEY = 'bs_font_size';

export const FONT_SIZE_LEVELS: FontSizeLevel[] = ['small', 'standard', 'large'];

const ZOOM_BY_LEVEL: Record<FontSizeLevel, number> = {
  small: 0.9,
  standard: 1,
  large: 1.1,
};

/** Desktop-only feature; the entry is hidden and the zoom dropped below this. */
const DESKTOP_MEDIA_QUERY = '(min-width: 768px)';

/** Presence of this attribute on <html> activates the scale CSS in index.css. */
const SCALE_ATTRIBUTE = 'data-bs-font-size';

const SCALE_VARIABLES = [
  '--bs-fs-zoom',
  '--bs-fs-popper-zoom',
  '--bs-fs-popper-unzoom',
  '--bs-vh',
  '--bs-dvh',
  '--bs-vw',
];

/**
 * How much of the page zoom `getBoundingClientRect()` has already applied,
 * measured rather than assumed.
 *
 * `zoom` predates its own specification, and engines disagree on this exact
 * point: current Blink reports rects in visual pixels (the zoom is baked in),
 * while older ones — the WeCom embedded browser among them — report the
 * pre-zoom layout pixels. Floating UI measures the trigger with this API and
 * writes the result back as a translate() on a wrapper that sits inside the
 * zoomed body, so the wrapper has to cancel exactly the part of the zoom the
 * measurement already carries: all of it on the newer engines, none of it on
 * the older ones. Compensating unconditionally is what leaves every popup off
 * by the zoom factor on the engines that never needed it.
 *
 * Returns the ratio of reported px to CSS px — the page zoom, or 1.
 */
function measureRectScale(): number {
  const probe = document.createElement('div');
  probe.style.cssText =
    'position:absolute;top:0;left:0;width:100px;height:0;visibility:hidden;pointer-events:none';
  document.body.appendChild(probe);
  const reported = probe.getBoundingClientRect().width;
  probe.remove();
  return reported > 0 ? reported / 100 : 1;
}

function isFontSizeLevel(value: unknown): value is FontSizeLevel {
  return value === 'small' || value === 'standard' || value === 'large';
}

function isDesktop(): boolean {
  return window.matchMedia(DESKTOP_MEDIA_QUERY).matches;
}

/**
 * Whether the font-size entry may be shown at all. The feature is desktop-only,
 * so both the menu entry and the zoom itself are gated on the same breakpoint.
 * Pair with subscribeFontSizeAvailability via useSyncExternalStore in React.
 */
export function isFontSizeAvailable(): boolean {
  return isDesktop();
}

/** Subscribe to desktop/mobile flips of the breakpoint above. */
export function subscribeFontSizeAvailability(onChange: () => void): () => void {
  const query = window.matchMedia(DESKTOP_MEDIA_QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

/** Stored level; missing or unreadable values fall back to standard. */
export function getFontSizeLevel(): FontSizeLevel {
  try {
    const value = localStorage.getItem(FONT_SIZE_STORAGE_KEY);
    return isFontSizeLevel(value) ? value : 'standard';
  } catch {
    return 'standard';
  }
}

/** Apply a level to <html>; standard and mobile viewports clear the scale. */
export function applyFontSizeLevel(level: FontSizeLevel) {
  const html = document.documentElement;
  if (level === 'standard' || !isDesktop()) {
    html.removeAttribute(SCALE_ATTRIBUTE);
    SCALE_VARIABLES.forEach((name) => html.style.removeProperty(name));
  } else {
    const zoom = ZOOM_BY_LEVEL[level];
    html.setAttribute(SCALE_ATTRIBUTE, level);
    html.style.setProperty('--bs-fs-zoom', String(zoom));
    // Probed only now that the zoom is live, so the probe gets the same
    // treatment a popup trigger would. Written as plain numbers rather than a
    // `calc(1 / var(--bs-fs-zoom))` in the stylesheet: older `zoom` parsers take
    // a bare number but drop the whole declaration when handed a calc(), which
    // would lose the compensation without a word.
    const rectScale = measureRectScale();
    html.style.setProperty('--bs-fs-popper-zoom', String(1 / rectScale));
    html.style.setProperty('--bs-fs-popper-unzoom', String(rectScale));
    html.style.setProperty('--bs-vh', `calc(100vh / ${zoom})`);
    html.style.setProperty('--bs-dvh', `calc(100dvh / ${zoom})`);
    html.style.setProperty('--bs-vw', `calc(100vw / ${zoom})`);
  }
  // The window itself did not change size, so no resize event fires — but the
  // logical viewport did, so every component that sizes itself from the
  // viewport has to recompute. Reuse the resize listeners they already have.
  window.dispatchEvent(new Event('resize'));
}

/**
 * Active zoom factor, 1 when no scale is applied.
 *
 * Needed because the DOM geometry APIs (innerWidth/innerHeight, clientX,
 * getBoundingClientRect) all report PHYSICAL pixels while anything written back
 * as a length inside the zoomed body is interpreted in LOGICAL pixels. Layout
 * math that measures the viewport and then sets a px size must divide by this.
 */
export function getDisplayScale(): number {
  const raw = document.documentElement.style.getPropertyValue('--bs-fs-zoom');
  const zoom = Number.parseFloat(raw);
  return Number.isFinite(zoom) && zoom > 0 ? zoom : 1;
}

/** Viewport size in the logical pixels the zoomed page actually lays out in. */
export function getLogicalViewport(): { width: number; height: number } {
  const zoom = getDisplayScale();
  return { width: window.innerWidth / zoom, height: window.innerHeight / zoom };
}

/**
 * How many of the units getBoundingClientRect() reports there are per CSS
 * pixel. This is the very factor measureRectScale() probes when a level is
 * applied; it is parked on --bs-fs-popper-unzoom, so read it back rather than
 * probing again (the probe costs a layout, and the answer cannot have changed
 * without applyFontSizeLevel running). 1 when no scale is applied.
 */
export function getRectScale(): number {
  const raw = document.documentElement.style.getPropertyValue('--bs-fs-popper-unzoom');
  const scale = Number.parseFloat(raw);
  return Number.isFinite(scale) && scale > 0 ? scale : 1;
}

/**
 * The window, expressed in the same units getBoundingClientRect() reports.
 *
 * This is the ONLY space in which a measured rect may be compared against the
 * window edges, and it is also the space Radix / Floating UI reads sideOffset
 * and alignOffset in, because those are added straight onto measured rects.
 *
 * Not interchangeable with getLogicalViewport(): that one answers "how big is
 * the page in the units I write CSS lengths in" and is what a component sizing
 * itself wants; this one answers "how big is the window in the units the rect I
 * just measured is quoted in". The two are the same number only on the engines
 * where the rect does NOT already carry the page zoom — mixing them up shifts
 * anything positioned against a window edge by the zoom factor, which is
 * invisible on those engines and plainly wrong everywhere else.
 */
export function getRectViewport(): { width: number; height: number } {
  const ratio = getRectScale() / getDisplayScale();
  return { width: window.innerWidth * ratio, height: window.innerHeight * ratio };
}

/** Persist and apply; returns false (without applying) when the write fails. */
export function saveFontSizeLevel(level: FontSizeLevel): boolean {
  try {
    localStorage.setItem(FONT_SIZE_STORAGE_KEY, level);
  } catch {
    return false;
  }
  applyFontSizeLevel(level);
  return true;
}

/**
 * Apply the stored level on boot, follow changes coming from other tabs or the
 * workspace app, and drop the zoom whenever the viewport enters mobile layout.
 */
export function initFontSize() {
  applyFontSizeLevel(getFontSizeLevel());
  window.addEventListener('storage', (e) => {
    if (e.key === FONT_SIZE_STORAGE_KEY || e.key === null) {
      applyFontSizeLevel(getFontSizeLevel());
    }
  });
  window
    .matchMedia(DESKTOP_MEDIA_QUERY)
    .addEventListener('change', () => applyFontSizeLevel(getFontSizeLevel()));
}
