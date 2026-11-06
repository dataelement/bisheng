import * as React from 'react';
import { createPortal } from 'react-dom';
import { Filled, Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Button } from '../Button/Button';
import {
  closeLatestNotification,
  closeNotification,
  getNotifications,
  isPrimaryNotificationViewport,
  registerNotificationViewport,
  subscribeNotifications,
  subscribeNotificationViewports,
  type NotificationItem,
  type NotificationType,
} from './notificationStore';

/**
 * Notifier — the single, always-mounted notification container
 * (组件-Notification通知提醒.md).
 *
 * Mount it once at the app root; everything else goes through the imperative
 * `notification` API. It stays in the DOM even when empty (§9) and renders
 * only in the FIRST mounted instance, so a docs page with several demos still
 * shows one stack in the top-right corner.
 */

type IconComponent = React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;

interface TypeMeta {
  Icon: IconComponent;
  iconColor: string;
  /** §9: only failures and warnings interrupt the screen reader. */
  assertive: boolean;
}

/**
 * Four types told apart by the icon alone — the card surface never changes
 * (§2/§4). Same semantic icon set as Toast; the colors are the functional
 * primaries (brand for info) and resolve through the dark ramps on their own.
 */
const TYPE_META: Record<NotificationType, TypeMeta> = {
  success: { Icon: Filled.CheckCircle as IconComponent, iconColor: 'text-success', assertive: false },
  error: { Icon: Filled.CloseCircle as IconComponent, iconColor: 'text-danger', assertive: true },
  warning: { Icon: Filled.Attention as IconComponent, iconColor: 'text-warning', assertive: true },
  info: { Icon: Filled.Info as IconComponent, iconColor: 'text-blue-main', assertive: false },
};

/** §7 — one easing for every notification transition (preset `ease-notice`). */
const EASE = 'ease-notice';
const EASE_CSS = 'cubic-bezier(0.2, 0, 0, 1)';
const EXPAND_MS = 240;

function canHover(): boolean {
  // §6: hovering pauses the countdown; touch has no hover, there the clock runs.
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(hover: hover) and (pointer: fine)').matches
  );
}

interface CardProps {
  item: NotificationItem;
  closeLabel: string;
  expandLabel: string;
}

function NotificationCard({ item, closeLabel, expandLabel }: CardProps) {
  const [entered, setEntered] = React.useState(false);
  const [paused, setPaused] = React.useState(false);
  const [overflowing, setOverflowing] = React.useState(false);
  const [expanded, setExpanded] = React.useState(false);
  const boxRef = React.useRef<HTMLDivElement>(null);
  const descRef = React.useRef<HTMLParagraphElement>(null);
  const collapsedHeightRef = React.useRef<number | null>(null);
  const { Icon, iconColor, assertive } = TYPE_META[item.type];

  // Slide in (§7). Reading the box flushes the offset start state so the class
  // swap below transitions from it. requestAnimationFrame would be the usual
  // trick, but it is frozen in a backgrounded tab — the card would then hang
  // at opacity 0 instead of being there when the user comes back (Toast §11.1).
  React.useLayoutEffect(() => {
    boxRef.current?.getBoundingClientRect();
    setEntered(true);
  }, []);

  // §5.2: the description shows three lines; only when more is hidden does the
  // 「展开」 button appear. Measured after mount and after every re-fire.
  React.useLayoutEffect(() => {
    if (expanded) {
      return;
    }
    const node = descRef.current;
    setOverflowing(node ? node.scrollHeight > node.clientHeight + 1 : false);
  }, [expanded, item.description, item.version]);

  // §7: expanding animates the height, 240ms. Line clamps cannot transition,
  // so the clamp is already gone when this runs; the height recorded at click
  // time is the start value and the natural height the end — the inline cap
  // is cleared afterwards so the viewport limit (§5.2) takes over.
  React.useLayoutEffect(() => {
    const node = descRef.current;
    const from = collapsedHeightRef.current;
    if (!expanded || !node || from === null) {
      return;
    }
    collapsedHeightRef.current = null;
    node.style.maxHeight = `${from}px`;
    node.style.overflow = 'hidden';
    node.getBoundingClientRect();
    node.style.transition = `max-height ${EXPAND_MS}ms ${EASE_CSS}`;
    node.style.maxHeight = `${node.scrollHeight}px`;
    const timer = window.setTimeout(() => {
      node.style.maxHeight = '';
      node.style.overflow = '';
      node.style.transition = '';
    }, EXPAND_MS);
    return () => window.clearTimeout(timer);
  }, [expanded]);

  // §6: the countdown restarts from zero on every re-trigger (version) and
  // whenever the pointer/focus leaves. `duration <= 0` means it stays put, and
  // an expanded card counts as "being read" — it waits for a manual close.
  React.useEffect(() => {
    if (item.closing || paused || expanded || item.duration <= 0) {
      return;
    }
    const timer = window.setTimeout(() => closeNotification(item.id), item.duration);
    return () => window.clearTimeout(timer);
  }, [expanded, item.closing, item.duration, item.id, item.version, paused]);

  const handleExpand = () => {
    collapsedHeightRef.current = descRef.current?.clientHeight ?? null;
    setExpanded(true);
  };

  const [primary, secondary] = item.actions;
  const hasActionRow = (!expanded && overflowing) || item.actions.length > 0;

  return (
    <div
      className={cn(
        // The wrapper collapses its own height so the cards below slide up in
        // 240ms instead of jumping (§7). pb-4 is the 16px stack gap (§3).
        'grid transition-[grid-template-rows,padding-bottom] duration-240',
        EASE,
        item.closing ? 'grid-rows-[0fr] pb-0' : 'grid-rows-[1fr] pb-4',
      )}
    >
      {/* Clip only while collapsing — a tight clipping box would also cut off
          `shadow-popup`, which is drawn outside the card's bounds. */}
      <div className={item.closing ? 'overflow-hidden' : 'overflow-visible'}>
        <div
          ref={boxRef}
          // §9: the role sits on each card; polite for success/info, assertive
          // for failures and warnings. Focus is never moved here.
          role={assertive ? 'alert' : 'status'}
          className={cn(
            // §4: fixed 360px, 16px padding, 12px radius, popup shadow, page
            // surface (white / dark) with a neutral outline in dark mode only.
            // §8: narrow viewports shrink it to the viewport minus 32px.
            'pointer-events-auto relative flex w-[360px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-48px)] gap-3 rounded-xl bg-bg-page p-4 shadow-popup transition-[opacity,transform] dark:border dark:border-border-base',
            EASE,
            entered && !item.closing
              ? 'translate-x-0 opacity-100 duration-240'
              : 'translate-x-4 opacity-0',
            item.closing ? 'duration-200' : 'duration-240',
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
          {/* Decorative (§9). A one-line-tall box centres the 16px icon on the
              first line of the title — or of the description when there is no
              title (§4). */}
          <span className="flex h-[var(--leading-body)] shrink-0 items-center self-start">
            <Icon aria-hidden className={cn('size-4', iconColor)} />
          </span>

          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            {item.title ? (
              // §5.1: one line, ellipsis; the close button's 24px box + 12px gap kept clear.
              <div className="truncate pr-9 text-body font-medium text-text-1">{item.title}</div>
            ) : null}
            {/* §4: secondary text under a title, primary text on its own.
                §5.2: clamped to 3 lines until expanded; expanded, it scrolls
                inside the viewport-capped card. */}
            <p
              ref={descRef}
              className={cn(
                'min-h-0 whitespace-pre-wrap break-words text-body',
                item.title ? 'mt-1 text-text-2' : 'pr-9 text-text-1',
                expanded ? 'overflow-y-auto' : 'line-clamp-3',
              )}
            >
              {item.description}
            </p>
            {hasActionRow ? (
              <div className="mt-3 flex shrink-0 items-center gap-2">
                {!expanded && overflowing ? (
                  <Button
                    color="primary"
                    variant="link"
                    size="small"
                    className="mr-auto px-0"
                    onClick={handleExpand}
                  >
                    {expandLabel}
                  </Button>
                ) : null}
                {/* §5.3: right-aligned, 24px; the primary action is the
                    次强调 filled button on the far right, the secondary a text
                    button beside it. Either one closes the card. */}
                {secondary ? (
                  <Button
                    color="default"
                    variant="text"
                    size="small"
                    className="ml-auto"
                    onClick={() => {
                      secondary.onClick();
                      closeNotification(item.id);
                    }}
                  >
                    {secondary.label}
                  </Button>
                ) : null}
                {primary ? (
                  <Button
                    color="primary"
                    variant="filled"
                    size="small"
                    className={secondary ? undefined : 'ml-auto'}
                    onClick={() => {
                      primary.onClick();
                      closeNotification(item.id);
                    }}
                  >
                    {primary.label}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>

          {/* §5.4: always there — the card may wait for the user, so it must
              always offer an exit. A borderless icon-only button (default ×
              text, 24px) whose 16px glyph is centred on the first text line
              and 16px from the right edge (§4): the 24px hit box sits 12px in,
              so the glyph lands where a bare icon would. */}
          <span className="absolute right-3 top-4 flex h-[var(--leading-body)] items-center">
            <Button
              color="default"
              variant="text"
              size="small"
              iconOnly
              aria-label={closeLabel}
              className="text-text-4 hover:text-text-2 [&_svg]:size-4"
              onClick={() => closeNotification(item.id)}
            >
              <Outlined.Close aria-hidden />
            </Button>
          </span>
        </div>
      </div>
    </div>
  );
}

export interface NotifierProps {
  /** Extra classes for the fixed container — position and z-index are fixed by spec. */
  className?: string;
  /** Accessible name of the close button (§9 「关闭通知」). Pass a localized string — the library holds no i18n. */
  closeLabel?: string;
  /** Label of the 「展开」 link that appears when the description is clipped (§5.2). */
  expandLabel?: string;
}

export function Notifier({ className, closeLabel = 'Close', expandLabel = 'Expand' }: NotifierProps) {
  const items = React.useSyncExternalStore(
    subscribeNotifications,
    getNotifications,
    getNotifications,
  );
  const tokenRef = React.useRef<symbol>();
  if (!tokenRef.current) {
    tokenRef.current = Symbol('notification-viewport');
  }
  const token = tokenRef.current;

  const [registered, setRegistered] = React.useState(false);
  React.useEffect(() => {
    const unregister = registerNotificationViewport(token);
    setRegistered(true);
    return unregister;
  }, [token]);

  const isPrimary = React.useSyncExternalStore(
    subscribeNotificationViewports,
    React.useCallback(() => isPrimaryNotificationViewport(token), [token]),
    React.useCallback(() => false, []),
  );

  // §6: ESC closes the newest one.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeLatestNotification();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  if (!registered || !isPrimary) {
    return null;
  }

  // Rendered into <body>: left at its mount point the container would inherit
  // the paint order of whatever section mounted it, and a positioned ancestor
  // could bury it under a dialog regardless of z-index (Toast §11.1).
  return createPortal(
    <div
      data-bisheng-notice=""
      className={cn(
        // §3: top-right, 24px from both edges, same tier as Toast (1200); the
        // two never overlap, so no separate layer. §8: 16px from the right on
        // viewports narrower than 408px. Newest at the bottom.
        'pointer-events-none fixed right-6 top-6 z-toast flex flex-col items-end max-[407px]:right-4',
        className,
      )}
    >
      {items.map((item) => (
        <NotificationCard
          key={item.id}
          item={item}
          closeLabel={closeLabel}
          expandLabel={expandLabel}
        />
      ))}
    </div>,
    document.body,
  );
}
