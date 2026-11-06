/**
 * Toast queue — the imperative half of the component (组件-Toast轻提示.md §11.1).
 *
 * The queue mechanics (cap of three, de-dupe by id, two-phase dismissal, the
 * single-viewport registry) are shared with Notification and live in
 * `utils/noticeQueue.ts`; this module only adds what is toast-specific — the
 * payload shape, the §6 lifetime formula and the `toast.*` API.
 */
import { createNoticeQueue, type QueueEntry } from '../../utils/noticeQueue';

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

export interface ToastItem
  extends QueueEntry,
    Required<Pick<ToastOptions, 'id' | 'duration' | 'closable'>> {
  type: ToastType;
  message: string;
  action?: ToastAction;
}

/** §6 lifetime formula. */
const BASE_MS = 3000;
const MIN_MS = 3000;
const MAX_MS = 10000;
const FREE_CHARS = 20;
const MS_PER_EXTRA_CHAR = 100;

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

const queue = createNoticeQueue<ToastItem>({
  // At most three at a time; a fourth pushes the oldest out (§3).
  maxVisible: 3,
  // Exit (160ms) + the 200ms others take to close the gap (§7).
  exitMs: 200,
});

export const subscribeToasts = queue.subscribe;
export const getToasts = queue.get;
/** Start the exit animation; the row leaves the DOM once it has played (§7). */
export const dismissToast = queue.dismiss;
/** ESC closes the newest one (§6). */
export const dismissLatestToast = queue.dismissLatest;
export const clearToasts = queue.clear;
export const subscribeViewports = queue.subscribeViewports;
export const registerViewport = queue.registerViewport;
export const isPrimaryViewport = queue.isPrimaryViewport;

function show(type: ToastType, message: string, options: ToastOptions = {}): string {
  const id = options.id ?? `${type}:${message}`;
  const duration = options.duration ?? computeDuration(message, Boolean(options.action));
  // 不自动关闭 must ship an exit (§5.3).
  const closable = options.closable ?? duration <= 0;
  return queue.push({ id, type, message, duration, closable, action: options.action });
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
