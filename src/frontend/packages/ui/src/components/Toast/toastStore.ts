/**
 * Toast queue — the imperative half of the component (组件-Toast轻提示.md §11.1).
 *
 * A toast is fired by an event, never rendered by a page, so the queue lives
 * outside React: business code calls `toast.success('已保存')` from anywhere
 * (event handlers, interceptors, non-component modules) and the single
 * `<Toaster />` mounted at the app root subscribes through
 * `useSyncExternalStore`. No state-management library is involved — the
 * library contract (packages/ui/AGENTS.md) forbids one.
 */

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface ToastAction {
  /** Link-button label. Must be a real follow-up ("撤销" / "查看") — never 关闭/取消/知道了 (§5.2). */
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  /**
   * De-dupe key (§3). Re-firing the same id updates the live toast and
   * restarts its timer instead of stacking a second one. Defaults to
   * `type + message`, so triple-clicking 保存 yields one 「已保存」.
   */
  id?: string;
  /**
   * Override the computed lifetime, in ms. `0` means "stays until dismissed"
   * and forces the close button (§5.3/§6) — note this INVERTS the legacy
   * client semantics, where 0 meant "hide immediately".
   */
  duration?: number;
  /** At most one action button (§5.2). Its presence doubles the lifetime. */
  action?: ToastAction;
  /** Force the close button. Implied by `duration: 0`. */
  closable?: boolean;
}

export interface ToastItem extends Required<Pick<ToastOptions, 'id' | 'duration' | 'closable'>> {
  type: ToastType;
  message: string;
  action?: ToastAction;
  /** Bumped whenever the same id is re-fired — the row watches it to restart its timer (§3). */
  version: number;
  /** Playing its exit animation; still in the DOM, no longer occupies a stack slot. */
  closing: boolean;
}

/** At most three at a time; a fourth pushes the oldest out (§3). */
const MAX_VISIBLE = 3;
/** §6 lifetime formula. */
const BASE_MS = 3000;
const MIN_MS = 3000;
const MAX_MS = 10000;
const FREE_CHARS = 20;
const MS_PER_EXTRA_CHAR = 100;
/** Exit (160ms) + the 200ms others take to close the gap (§7). */
const EXIT_MS = 200;

/**
 * §6: 3s, +100ms per character past 20, doubled when there is an action button,
 * then clamped to 3–10s. Characters are counted by code point so CJK counts per
 * glyph and an emoji counts once.
 */
export function computeDuration(message: string, hasAction: boolean): number {
  const chars = Array.from(message).length;
  let ms = BASE_MS + Math.max(0, chars - FREE_CHARS) * MS_PER_EXTRA_CHAR;
  if (hasAction) {
    ms *= 2;
  }
  return Math.min(Math.max(ms, MIN_MS), MAX_MS);
}

let items: ToastItem[] = [];
const listeners = new Set<() => void>();
const removalTimers = new Map<string, ReturnType<typeof setTimeout>>();

function emit(next: ToastItem[]) {
  items = next;
  listeners.forEach((listener) => listener());
}

export function subscribeToasts(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getToasts(): ToastItem[] {
  return items;
}

function scheduleRemoval(id: string) {
  const pending = removalTimers.get(id);
  if (pending) {
    clearTimeout(pending);
  }
  removalTimers.set(
    id,
    setTimeout(() => {
      removalTimers.delete(id);
      emit(items.filter((item) => item.id !== id));
    }, EXIT_MS),
  );
}

/** Start the exit animation; the row leaves the DOM once it has played (§7). */
export function dismissToast(id: string) {
  if (!items.some((item) => item.id === id && !item.closing)) {
    return;
  }
  emit(items.map((item) => (item.id === id ? { ...item, closing: true } : item)));
  scheduleRemoval(id);
}

/** ESC closes the newest one (§6). */
export function dismissLatestToast() {
  const live = items.filter((item) => !item.closing);
  const latest = live[live.length - 1];
  if (latest) {
    dismissToast(latest.id);
  }
}

export function clearToasts() {
  removalTimers.forEach((timer) => clearTimeout(timer));
  removalTimers.clear();
  emit([]);
}

function show(type: ToastType, message: string, options: ToastOptions = {}): string {
  const id = options.id ?? `${type}:${message}`;
  const duration = options.duration ?? computeDuration(message, Boolean(options.action));
  // 不自动关闭 must ship an exit (§5.3).
  const closable = options.closable ?? duration <= 0;
  const next: Omit<ToastItem, 'version'> = {
    id,
    type,
    message,
    duration,
    closable,
    action: options.action,
    closing: false,
  };

  const existing = items.find((item) => item.id === id && !item.closing);
  if (existing) {
    // §3: same message fired again → update in place and restart the clock.
    emit(items.map((item) => (item === existing ? { ...next, version: item.version + 1 } : item)));
    return id;
  }

  let queued = [...items, { ...next, version: 0 }];
  const live = queued.filter((item) => !item.closing);
  if (live.length > MAX_VISIBLE) {
    // §3: the fourth pushes the oldest out right away, so the newest is always visible.
    const oldest = live[0];
    queued = queued.map((item) => (item === oldest ? { ...item, closing: true } : item));
    scheduleRemoval(oldest.id);
  }
  emit(queued);
  return id;
}

export interface ToastPayload extends ToastOptions {
  type?: ToastType;
  message: string;
}

/**
 * Imperative API. `toast.info` is the fallback when the result has no
 * success/failure reading — dressing a failure up as info is the one thing
 * §2 rules out.
 */
export const toast = {
  success: (message: string, options?: ToastOptions) => show('success', message, options),
  error: (message: string, options?: ToastOptions) => show('error', message, options),
  warning: (message: string, options?: ToastOptions) => show('warning', message, options),
  info: (message: string, options?: ToastOptions) => show('info', message, options),
  /** Object form, for call sites whose type is a runtime value. */
  show: ({ type = 'info', message, ...options }: ToastPayload) => show(type, message, options),
  dismiss: dismissToast,
  dismissLatest: dismissLatestToast,
  clear: clearToasts,
};

/* ------------------------------------------------------------------ *
 * Viewport registry — one visible container, however many are mounted.
 * Demo pages (and StrictMode's double mount) can render several
 * <Toaster />s; only the first one registered paints, so a toast never
 * appears twice.
 * ------------------------------------------------------------------ */

const viewports: symbol[] = [];
const viewportListeners = new Set<() => void>();

export function subscribeViewports(listener: () => void): () => void {
  viewportListeners.add(listener);
  return () => {
    viewportListeners.delete(listener);
  };
}

export function registerViewport(token: symbol): () => void {
  viewports.push(token);
  viewportListeners.forEach((listener) => listener());
  return () => {
    const index = viewports.indexOf(token);
    if (index >= 0) {
      viewports.splice(index, 1);
    }
    viewportListeners.forEach((listener) => listener());
  };
}

export function isPrimaryViewport(token: symbol): boolean {
  return viewports[0] === token;
}
