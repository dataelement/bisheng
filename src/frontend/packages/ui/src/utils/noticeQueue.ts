/**
 * Notice queue — the shared imperative core behind Toast and Notification.
 *
 * Both components are fired by events rather than rendered by pages, so their
 * queues live outside React: business code calls `toast.success(...)` /
 * `notification.open(...)` from anywhere and the single container mounted at
 * the app root subscribes through `useSyncExternalStore`. The queue rules are
 * identical for both (组件-Toast轻提示.md §3 / 组件-Notification通知提醒.md §3):
 *
 * - a capped number of live entries; one more pushes the OLDEST out at once;
 * - re-firing an existing id updates it in place and bumps `version`, which
 *   the row watches to restart its countdown — never a duplicate;
 * - dismissal is two-phase: `closing: true` plays the exit motion while the
 *   entry stays in the DOM, then it is removed once the motion has finished.
 *
 * No state-management library is involved — the library contract
 * (packages/ui/AGENTS.md) forbids one.
 */

export interface QueueEntry {
  /** De-dupe key. */
  id: string;
  /** Bumped whenever the same id is re-fired. */
  version: number;
  /** Playing its exit animation; still in the DOM, no longer occupies a slot. */
  closing: boolean;
}

export interface NoticeQueueConfig {
  /** Live entries allowed at once; the next one evicts the oldest. */
  maxVisible: number;
  /** How long a closing entry stays in the DOM for its exit + gap-close motion. */
  exitMs: number;
}

export interface NoticeQueue<T extends QueueEntry> {
  subscribe: (listener: () => void) => () => void;
  get: () => T[];
  /**
   * Add or update. Returns the entry's id. An existing live entry with the same
   * id is replaced in place (version + 1); otherwise the entry is appended and
   * the oldest live one is evicted when the cap is exceeded.
   */
  push: (entry: Omit<T, 'version' | 'closing'>) => string;
  /** Start the exit animation; the entry leaves the DOM once it has played. */
  dismiss: (id: string) => void;
  /** ESC closes the newest one. */
  dismissLatest: () => void;
  /** Drop everything immediately, no exit motion. */
  clear: () => void;
  /* Viewport registry — one visible container, however many are mounted.
     Demo pages (and StrictMode's double mount) can render several containers;
     only the first one registered paints, so an entry never appears twice. */
  subscribeViewports: (listener: () => void) => () => void;
  registerViewport: (token: symbol) => () => void;
  isPrimaryViewport: (token: symbol) => boolean;
}

export function createNoticeQueue<T extends QueueEntry>({
  maxVisible,
  exitMs,
}: NoticeQueueConfig): NoticeQueue<T> {
  let items: T[] = [];
  const listeners = new Set<() => void>();
  const removalTimers = new Map<string, ReturnType<typeof setTimeout>>();

  function emit(next: T[]) {
    items = next;
    listeners.forEach((listener) => listener());
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
      }, exitMs),
    );
  }

  function dismiss(id: string) {
    if (!items.some((item) => item.id === id && !item.closing)) {
      return;
    }
    emit(items.map((item) => (item.id === id ? { ...item, closing: true } : item)));
    scheduleRemoval(id);
  }

  function push(entry: Omit<T, 'version' | 'closing'>): string {
    const existing = items.find((item) => item.id === entry.id && !item.closing);
    if (existing) {
      // Same id fired again → update in place and restart the clock.
      emit(
        items.map((item) =>
          item === existing ? ({ ...entry, closing: false, version: item.version + 1 } as T) : item,
        ),
      );
      return entry.id;
    }

    let queued: T[] = [...items, { ...entry, closing: false, version: 0 } as T];
    const live = queued.filter((item) => !item.closing);
    if (live.length > maxVisible) {
      // One over the cap pushes the oldest out right away, so the newest is always visible.
      const oldest = live[0];
      queued = queued.map((item) => (item === oldest ? { ...item, closing: true } : item));
      scheduleRemoval(oldest.id);
    }
    emit(queued);
    return entry.id;
  }

  const viewports: symbol[] = [];
  const viewportListeners = new Set<() => void>();

  return {
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    get: () => items,
    push,
    dismiss,
    dismissLatest() {
      const live = items.filter((item) => !item.closing);
      const latest = live[live.length - 1];
      if (latest) {
        dismiss(latest.id);
      }
    },
    clear() {
      removalTimers.forEach((timer) => clearTimeout(timer));
      removalTimers.clear();
      emit([]);
    },
    subscribeViewports(listener) {
      viewportListeners.add(listener);
      return () => {
        viewportListeners.delete(listener);
      };
    },
    registerViewport(token) {
      viewports.push(token);
      viewportListeners.forEach((listener) => listener());
      return () => {
        const index = viewports.indexOf(token);
        if (index >= 0) {
          viewports.splice(index, 1);
        }
        viewportListeners.forEach((listener) => listener());
      };
    },
    isPrimaryViewport: (token) => viewports[0] === token,
  };
}
