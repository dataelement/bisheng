/**
 * Notification queue — the imperative half of the component
 * (组件-Notification通知提醒.md §10.1).
 *
 * A notification reports something the user did NOT just do (a background
 * task finished, someone added them to a space), so it is fired from event
 * handlers, websocket callbacks and interceptors — never rendered by a page.
 * The queue mechanics are shared with Toast (`utils/noticeQueue.ts`); this
 * module adds the payload shape, the §6 lifetime defaults and the
 * `notification.*` API.
 */
import { createNoticeQueue, type QueueEntry } from '../../utils/noticeQueue';

export type NotificationType = 'success' | 'error' | 'warning' | 'info';

export interface NotificationAction {
  /** Button label. Must be a real follow-up (「查看」「重试」「前往」) — never 关闭/知道了 (§5.3). */
  label: string;
  onClick: () => void;
}

export interface NotificationOptions {
  /** Which icon it carries (§2). Defaults to `info`. */
  type?: NotificationType;
  /** One line saying what happened, no full stop; clipped to a single line (§5.1). */
  title?: string;
  /** Required. A complete sentence: what happened and what the user can do (§5.2). */
  description: string;
  /**
   * At most two (§5.3). The FIRST is the primary action (次强调 filled button,
   * rendered rightmost); the second is the text button to its left. A third
   * one is dropped.
   */
  actions?: NotificationAction[];
  /**
   * Lifetime in ms. Defaults to 5000, or 10000 when there are actions (§6).
   * `0` means "stays until dismissed" — reserve it for things the user must
   * deal with. Expanding a clipped description switches the live card to 0.
   */
  duration?: number;
  /**
   * De-dupe key (§3). Re-firing the same id updates the live card and restarts
   * its timer. Defaults to `type + title + description`.
   */
  id?: string;
  /** Called once the card has left — by timer, close button, ESC, an action, or eviction. */
  onClose?: () => void;
}

export interface NotificationItem extends QueueEntry {
  type: NotificationType;
  title?: string;
  description: string;
  actions: NotificationAction[];
  duration: number;
  onClose?: () => void;
}

/** §6 defaults. */
export const DEFAULT_DURATION_MS = 5000;
export const WITH_ACTIONS_DURATION_MS = 10000;
const MAX_ACTIONS = 2;

const queue = createNoticeQueue<NotificationItem>({
  // At most three at a time; a fourth pushes the oldest out (§3).
  maxVisible: 3,
  // Exit (200ms) runs inside the 240ms the others take to close the gap (§7).
  exitMs: 240,
});

export const subscribeNotifications = queue.subscribe;
export const getNotifications = queue.get;
export const subscribeNotificationViewports = queue.subscribeViewports;
export const registerNotificationViewport = queue.registerViewport;
export const isPrimaryNotificationViewport = queue.isPrimaryViewport;

/** Start the exit animation and fire `onClose`; the card leaves the DOM once it has played (§7). */
export function closeNotification(id: string) {
  const target = queue.get().find((item) => item.id === id && !item.closing);
  if (!target) {
    return;
  }
  queue.dismiss(id);
  target.onClose?.();
}

/** ESC closes the newest one (§6). */
export function closeLatestNotification() {
  const live = queue.get().filter((item) => !item.closing);
  const latest = live[live.length - 1];
  if (latest) {
    closeNotification(latest.id);
  }
}

export function closeAllNotifications() {
  const live = queue.get().filter((item) => !item.closing);
  queue.clear();
  live.forEach((item) => item.onClose?.());
}

function open(options: NotificationOptions): string {
  const { type = 'info', title, description, onClose } = options;
  const actions = (options.actions ?? []).slice(0, MAX_ACTIONS);
  const duration =
    options.duration ?? (actions.length > 0 ? WITH_ACTIONS_DURATION_MS : DEFAULT_DURATION_MS);
  const id = options.id ?? `${type}:${title ?? ''}:${description}`;

  const liveBefore = queue.get().filter((item) => !item.closing);
  const returned = queue.push({ id, type, title, description, actions, duration, onClose });
  // The queue flips the oldest to `closing` when the cap is exceeded (§3);
  // its owner is told the same way as for any other exit.
  const after = queue.get();
  liveBefore.forEach((previous) => {
    if (after.find((item) => item.id === previous.id)?.closing) {
      previous.onClose?.();
    }
  });
  return returned;
}

type ShortcutOptions = Omit<NotificationOptions, 'type' | 'description'>;

/**
 * Imperative API. `notification.info` is the fallback when the event has no
 * success/failure reading — dressing a failure up as info is the one thing
 * §2 rules out.
 */
export const notification = {
  open,
  success: (description: string, options?: ShortcutOptions) =>
    open({ ...options, type: 'success', description }),
  error: (description: string, options?: ShortcutOptions) =>
    open({ ...options, type: 'error', description }),
  warning: (description: string, options?: ShortcutOptions) =>
    open({ ...options, type: 'warning', description }),
  info: (description: string, options?: ShortcutOptions) =>
    open({ ...options, type: 'info', description }),
  close: closeNotification,
  closeLatest: closeLatestNotification,
  closeAll: closeAllNotifications,
};
