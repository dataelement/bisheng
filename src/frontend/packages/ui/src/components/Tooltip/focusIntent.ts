import * as React from 'react';

const NAVIGATION_KEYS = new Set(['Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown']);
const keyboardFocusEvents = new WeakSet<Event>();

interface FocusTracker {
  users: number;
  dispose: () => void;
}

// Share capture listeners across providers, including standalone Tooltip fallbacks.
const trackers = new WeakMap<Document, FocusTracker>();

function subscribe(document: Document) {
  let tracker = trackers.get(document);
  if (!tracker) {
    let keyboardNavigation = false;
    const handleKeyDown = (event: KeyboardEvent) => {
      keyboardNavigation = NAVIGATION_KEYS.has(event.key) && !event.altKey && !event.ctrlKey && !event.metaKey;
    };
    const handlePointerDown = () => { keyboardNavigation = false; };
    const handleFocus = (event: FocusEvent) => {
      if (keyboardNavigation) keyboardFocusEvents.add(event);
      // Consume one focus move; later popup restoration is a separate action.
      keyboardNavigation = false;
    };
    document.addEventListener('keydown', handleKeyDown, true);
    document.addEventListener('pointerdown', handlePointerDown, true);
    document.addEventListener('focusin', handleFocus, true);
    tracker = {
      users: 0,
      dispose: () => {
        document.removeEventListener('keydown', handleKeyDown, true);
        document.removeEventListener('pointerdown', handlePointerDown, true);
        document.removeEventListener('focusin', handleFocus, true);
      },
    };
    trackers.set(document, tracker);
  }
  tracker.users += 1;
  return () => {
    tracker.users -= 1;
    if (tracker.users === 0) {
      tracker.dispose();
      trackers.delete(document);
    }
  };
}

export function useTooltipFocusIntent(trigger: React.RefObject<HTMLElement>) {
  React.useEffect(() => {
    const document = trigger.current?.ownerDocument;
    if (document) return subscribe(document);
  }, [trigger]);
  return (event: Event) => keyboardFocusEvents.has(event);
}
