import * as React from 'react';
import { createPortal } from 'react-dom';
import { Filled, Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Button } from '../Button/Button';
import {
  dismissLatestToast,
  dismissToast,
  getToasts,
  isPrimaryViewport,
  registerViewport,
  subscribeToasts,
  subscribeViewports,
  type ToastItem,
  type ToastType,
} from './toastStore';

/**
 * Toaster — the single, always-mounted toast container (组件-Toast轻提示.md).
 *
 * Mount it once at the app root; everything else goes through the imperative
 * `toast` API. It stays in the DOM even when empty, because the screen-reader
 * live regions have to pre-exist the message to announce it (§9).
 *
 * Rendering only happens in the FIRST mounted instance (toastStore's viewport
 * registry), so a docs page with several demos still shows one stack.
 */

type IconComponent = React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;

interface TypeMeta {
  Icon: IconComponent;
  /** Tinted surface (§4). Dark mode has no tint ramp yet — see the note below. */
  surface: string;
  iconColor: string;
  /** §9: only failures and warnings interrupt the screen reader. */
  assertive: boolean;
}

/**
 * Four types, each with its own icon — never text-only, so the semantics survive
 * for users who can't separate the colors (§2).
 *
 * Dark mode: the `*-tint` tokens are light-mode values (功能色 dark ramp is still
 * open — 组件-Toast轻提示.md §12), and 主文字色 flips to near-white there, so the
 * tint would go unreadable. Until that decision lands, dark mode re-derives the
 * surface from the SAME functional token at low alpha — still token-driven, no
 * bare hex.
 */
const TYPE_META: Record<ToastType, TypeMeta> = {
  success: {
    Icon: Filled.CheckCircle as IconComponent,
    surface: 'bg-success-tint dark:bg-success/15',
    iconColor: 'text-success',
    assertive: false,
  },
  error: {
    Icon: Filled.CloseCircle as IconComponent,
    surface: 'bg-danger-tint dark:bg-danger/15',
    iconColor: 'text-danger',
    assertive: true,
  },
  warning: {
    Icon: Filled.Attention as IconComponent,
    surface: 'bg-warning-tint dark:bg-warning/15',
    iconColor: 'text-warning',
    assertive: true,
  },
  info: {
    Icon: Filled.Info as IconComponent,
    surface: 'bg-blue-50 dark:bg-blue-500/15',
    iconColor: 'text-blue-main',
    assertive: false,
  },
};

/** §7 — one easing for every toast transition; faster than dialogs by design. */
const EASE = 'ease-[cubic-bezier(0.2,0,0,1)]';

function canHover(): boolean {
  // §6/§8: hovering pauses the countdown, but touch has no hover — there the
  // clock just runs.
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(hover: hover) and (pointer: fine)').matches
  );
}

function ToastRow({ item, closeLabel }: { item: ToastItem; closeLabel: string }) {
  const [entered, setEntered] = React.useState(false);
  const [paused, setPaused] = React.useState(false);
  const [multiline, setMultiline] = React.useState(false);
  const textRef = React.useRef<HTMLSpanElement>(null);
  const boxRef = React.useRef<HTMLDivElement>(null);
  const meta = TYPE_META[item.type];
  const { Icon } = meta;

  // §4: a single line is exactly 40px tall with no vertical padding; once the
  // text wraps it switches to 12px top/bottom and grows. An inline span reports
  // one client rect per line box, which is the cheapest way to tell them apart.
  React.useLayoutEffect(() => {
    const node = textRef.current;
    setMultiline(node ? node.getClientRects().length > 1 : false);
  }, [item.message, item.version]);

  // Slide in (§7). Reading the box flushes the offset start state so the class
  // swap below transitions from it. requestAnimationFrame would be the usual
  // trick, but it is frozen in a backgrounded tab — the toast would then hang
  // at opacity 0 forever instead of being there when the user comes back.
  React.useLayoutEffect(() => {
    boxRef.current?.getBoundingClientRect();
    setEntered(true);
  }, []);

  // §6: the countdown restarts from zero on every re-trigger (version) and
  // whenever the pointer/focus leaves. `duration <= 0` means it stays put.
  React.useEffect(() => {
    if (item.closing || paused || item.duration <= 0) {
      return;
    }
    const timer = window.setTimeout(() => dismissToast(item.id), item.duration);
    return () => window.clearTimeout(timer);
  }, [item.closing, item.duration, item.id, item.version, paused]);

  return (
    <div
      className={cn(
        // The wrapper collapses its own height so the toasts below slide up in
        // 200ms instead of jumping (§7). pb-2 is the 8px stack gap (§3).
        'grid transition-[grid-template-rows,padding-bottom] duration-200',
        EASE,
        item.closing ? 'grid-rows-[0fr] pb-0' : 'grid-rows-[1fr] pb-2',
      )}
    >
      {/* The 0fr collapse only bites when the row clips its content — but a
          clipping box that fits the toast exactly also cuts off `shadow-popup`,
          which is drawn entirely OUTSIDE those bounds. So clip only while the
          row is collapsing; the toast has faded out by then anyway. */}
      <div className={item.closing ? 'overflow-hidden' : 'overflow-visible'}>
        <div className="flex justify-center">
          <div
            ref={boxRef}
            className={cn(
              'pointer-events-auto flex w-max max-w-[480px] items-center rounded-xl px-4 shadow-popup transition-[opacity,transform] max-md:w-full max-md:max-w-none',
              multiline ? 'py-3' : 'min-h-10 py-[9px]',
              meta.surface,
              EASE,
              entered && !item.closing
                ? 'translate-y-0 opacity-100 duration-200'
                : '-translate-y-2 opacity-0',
              item.closing ? 'duration-[160ms]' : 'duration-200',
            )}
            onMouseEnter={() => {
              if (canHover()) {
                setPaused(true);
              }
            }}
            onMouseLeave={() => setPaused(false)}
            onFocus={() => setPaused(true)}
            onBlur={() => setPaused(false)}
          >
            {/* Decorative: the live region already says which kind it is (§9). */}
            <Icon aria-hidden className={cn('size-4 shrink-0', meta.iconColor)} />
            {/* 主文字色, not the semantic color — a whole sentence in orange or
                green is hard to read on a tinted surface (§4). */}
            <div className="ml-2 min-w-0 text-body text-text-1">
              <span ref={textRef} className="whitespace-pre-wrap break-words">
                {item.message}
              </span>
            </div>
            {item.action ? (
              <Button
                color="primary"
                variant="link"
                size="small"
                // 16px from the copy (§5.2); btn-touch-hit gives the 44px touch
                // target without changing the visual size (§8).
                className="btn-touch-hit ml-4 shrink-0 px-0"
                onClick={() => {
                  item.action?.onClick();
                  dismissToast(item.id);
                }}
              >
                {item.action.label}
              </Button>
            ) : null}
            {item.closable ? (
              <button
                type="button"
                aria-label={closeLabel}
                className="btn-touch-hit relative ml-2 shrink-0 text-text-3 transition-colors hover:text-text-1"
                onClick={() => dismissToast(item.id)}
              >
                <Outlined.Close className="size-3.5" />
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export interface ToasterProps {
  /** Extra classes for the fixed container — position and z-index are fixed by spec. */
  className?: string;
  /**
   * Accessible name of the close button (only rendered for toasts that don't
   * auto-close, §5.3). Pass a localized string — the library holds no i18n.
   */
  closeLabel?: string;
}

export function Toaster({ className, closeLabel = 'Close' }: ToasterProps) {
  const items = React.useSyncExternalStore(subscribeToasts, getToasts, getToasts);
  const tokenRef = React.useRef<symbol>();
  if (!tokenRef.current) {
    tokenRef.current = Symbol('toast-viewport');
  }
  const token = tokenRef.current;

  const [registered, setRegistered] = React.useState(false);
  React.useEffect(() => {
    const unregister = registerViewport(token);
    setRegistered(true);
    return unregister;
  }, [token]);

  const isPrimary = React.useSyncExternalStore(
    subscribeViewports,
    React.useCallback(() => isPrimaryViewport(token), [token]),
    React.useCallback(() => false, []),
  );

  // §6: ESC closes the newest one.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        dismissLatestToast();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  const live = items.filter((item) => !item.closing);
  const latestOf = (assertive: boolean) =>
    [...live].reverse().find((item) => TYPE_META[item.type].assertive === assertive)?.message ?? '';

  if (!registered || !isPrimary) {
    return null;
  }

  // Rendered into <body> (§3: always on top). Left where it is declared, the
  // container inherits the paint order of whatever page section mounted it —
  // any positioned ancestor between it and <body> can bury it under sticky
  // chrome or a dialog no matter how large its z-index is.
  return createPortal(
    <div
      className={cn(
        // Always top-center, 16px below the viewport edge, above everything —
        // a toast fired from inside a dialog has to be visible (§3). The exact
        // layer number lands with the Modal-era z-index table (§11.7).
        'pointer-events-none fixed inset-x-0 top-4 z-[9999] flex flex-col items-stretch max-md:px-4',
        className,
      )}
    >
      {/* §9: the live regions are permanent; only their text changes, which is
          what actually gets announced. Success/info are polite, failures and
          warnings interrupt. */}
      <div role="status" aria-live="polite" className="sr-only">
        {latestOf(false)}
      </div>
      <div role="alert" aria-live="assertive" className="sr-only">
        {latestOf(true)}
      </div>
      {items.map((item) => (
        <ToastRow key={item.id} item={item} closeLabel={closeLabel} />
      ))}
    </div>,
    document.body,
  );
}
