import * as React from 'react';
import { Filled, Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Button } from '../Button/Button';

/**
 * Alert — one line of copy embedded in the page, saying what state this page
 * or this block is in (组件-Alert警告提示.md v1).
 *
 * It does not float, does not cover anything and never leaves on its own: the
 * state it reports is still true until the business clears it or the user
 * closes it (§1). That is the whole dividing line against the rest of the
 * notice family — a Toast reports the click the user just made, a Notification
 * reports something the system did, a Modal demands a decision now.
 *
 * Mounted as JSX and driven by the host's own state (落地 §9.1): there is no
 * imperative `alert.warning(…)` twin of the Toast API, because the thing being
 * shown is not an event that happened once, it is a condition that holds.
 *
 * Baked in per spec: the four types and their tinted surfaces (§2), the 8px
 * margin that keeps the radius off the container edge (§3), the 40px
 * single-line box that grows to 12px padding as soon as there is a title or a
 * second line (§4), the 1-line title / 2-line body clamps (§5), at most two
 * text actions (§5.3), and the 200ms fade-and-collapse on close (§6). Every
 * string arrives as a prop — the library holds no i18n.
 */

export type AlertType = 'info' | 'success' | 'warning' | 'error';

export interface AlertAction {
  label: string;
  /**
   * §5.3: the actual move that deals with the state —「去配置」「查看」「重试」.
   * Never「关闭」「知道了」; that is what `closable` is for. The alert does NOT
   * close itself when this fires — the state is only gone once the host says so.
   */
  onClick: () => void;
}

export interface AlertProps {
  /** §2 — `info` when in doubt; every type carries its icon, there is no text-only form. */
  type?: AlertType;
  /** §5.1 — one line, no full stop. Skip it rather than padding one sentence into two. */
  title?: string;
  /**
   * §5.2 — required, plain text only. Says what the state IS and what the user
   * can do about it; links and jumps go in `actions`, which is why this is a
   * `string` and not a node.
   */
  description: string;
  /** §5.3 — at most two; `actions[0]` is the primary one. */
  actions?: AlertAction[];
  /**
   * §5.4 — off by default: a state the user has to deal with should not be
   * dismissable. Turn it on only for「knowing is enough」notices.
   */
  closable?: boolean;
  /**
   * Fired after the collapse finishes (§6). Whether「closed」survives a reload
   * is the host's call — the component stores nothing (落地 §9.7).
   *
   * Closing retires THIS instance: it renders nothing from then on, even if
   * the props change. Bringing the alert back is a remount, which is what the
   * host's own `state && <Alert …/>` already does.
   */
  onClose?: () => void;
  /**
   * §8 — set it when the alert is inserted in reaction to something the user
   * just did, so a screen reader announces it: failures and warnings interrupt
   * (`role="alert"`), successes and info wait their turn (`role="status"`).
   * An alert that is simply part of the page gets no live region at all — it is
   * read in document order.
   */
  live?: boolean;
  /** Accessible name of the close button (§8 「关闭」, i18n key `com_ui_close`). */
  closeLabel?: string;
  /** Extra classes for the outer box, which carries the 8px margin (§3). */
  className?: string;
}

type IconComponent = React.ComponentType<{ className?: string; 'aria-hidden'?: boolean }>;

interface TypeMeta {
  Icon: IconComponent;
  /** §4: a tinted surface, no border and no shadow — it sits IN the page. */
  surface: string;
  iconColor: string;
  /** §8: only failures and warnings interrupt the screen reader. */
  assertive: boolean;
}

/**
 * Four types, each with its own icon — never color alone, so the semantics
 * survive for readers who cannot separate them (§2). Same icon set and the
 * same 16px size as Toast and Notification: one family, one ladder.
 *
 * Dark mode needs no per-type patch: the `*-tint` tokens (and the brand
 * blue-50) resolve through the dark ramps in tokens.css, so these classes
 * serve both modes.
 */
const TYPE_META: Record<AlertType, TypeMeta> = {
  info: {
    Icon: Filled.Info as IconComponent,
    surface: 'bg-blue-50',
    iconColor: 'text-blue-main',
    assertive: false,
  },
  success: {
    Icon: Filled.CheckCircle as IconComponent,
    surface: 'bg-success-tint',
    iconColor: 'text-success',
    assertive: false,
  },
  warning: {
    Icon: Filled.Attention as IconComponent,
    surface: 'bg-warning-tint',
    iconColor: 'text-warning',
    assertive: true,
  },
  error: {
    Icon: Filled.CloseCircle as IconComponent,
    surface: 'bg-danger-tint',
    iconColor: 'text-danger',
    assertive: true,
  },
};

/** §6 — the one easing the notice family shares (preset `ease-notice`). */
const EASE = 'ease-notice';
/** §6 — fade + height collapse. Keep in step with the `duration-200` classes below. */
const CLOSE_MS = 200;
/** §5.3 — two is the ceiling; a third exit means the copy is doing too much. */
const MAX_ACTIONS = 2;

interface TextFlags {
  /** The body wrapped, so the box leaves the 40px single-line form (§4). */
  wrapped: boolean;
  titleClipped: boolean;
  descriptionClipped: boolean;
}

const NO_CLIP: TextFlags = { wrapped: false, titleClipped: false, descriptionClipped: false };

export function Alert({
  type = 'info',
  title,
  description,
  actions = [],
  closable = false,
  onClose,
  live = false,
  closeLabel = 'Close',
  className,
}: AlertProps) {
  const [flags, setFlags] = React.useState<TextFlags>(NO_CLIP);
  const [closing, setClosing] = React.useState(false);
  const [dismissed, setDismissed] = React.useState(false);
  const textRef = React.useRef<HTMLDivElement>(null);
  const titleRef = React.useRef<HTMLDivElement>(null);
  const descriptionRef = React.useRef<HTMLParagraphElement>(null);
  const onCloseRef = React.useRef(onClose);
  const meta = TYPE_META[type];
  const { Icon } = meta;

  // The host usually passes a fresh arrow function every render; read the
  // callback through a ref so the close timer below is not restarted — and
  // therefore never fires — on an unrelated re-render.
  React.useLayoutEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // §4 / §5: the layout needs to know whether the body takes one line, and the
  // `title` fallback needs to know whether anything is actually cut off.
  // Comparing the paragraph's height against ONE line of its own line-height
  // settles the first question without reading the container, so switching the
  // padding cannot feed back into the measurement.
  React.useLayoutEffect(() => {
    const node = descriptionRef.current;
    if (!node) {
      return;
    }
    const measure = () => {
      const lineHeight = Number.parseFloat(window.getComputedStyle(node).lineHeight);
      const next: TextFlags = {
        wrapped:
          Number.isFinite(lineHeight) && lineHeight > 0
            ? node.getBoundingClientRect().height > lineHeight + 1
            : false,
        titleClipped: titleRef.current
          ? titleRef.current.scrollHeight > titleRef.current.clientHeight + 1
          : false,
        descriptionClipped: node.scrollHeight > node.clientHeight + 1,
      };
      setFlags((prev) =>
        prev.wrapped === next.wrapped &&
        prev.titleClipped === next.titleClipped &&
        prev.descriptionClipped === next.descriptionClipped
          ? prev
          : next,
      );
    };
    measure();
    if (typeof ResizeObserver === 'undefined') {
      return;
    }
    // The alert is as wide as its container, so a window resize is what
    // decides how many lines the body takes — measuring only on mount would
    // leave a two-line body inside the 40px box.
    const observer = new ResizeObserver(measure);
    if (textRef.current) {
      observer.observe(textRef.current);
    }
    return () => observer.disconnect();
  }, [description, title]);

  // §6: fade out while the height collapses, then unmount and report. The
  // callback runs at the END so a host that drops the alert on `onClose` does
  // not cut the animation it is there to play.
  React.useEffect(() => {
    if (!closing) {
      return;
    }
    const timer = window.setTimeout(() => {
      setDismissed(true);
      onCloseRef.current?.();
    }, CLOSE_MS);
    return () => window.clearTimeout(timer);
  }, [closing]);

  // §5.3: render the first two and say so out loud. The library has no
  // dev-only channel (no node / vite env types by contract), so this warns
  // wherever it happens — it only fires on misuse, and silently dropping an
  // action the caller wrote is worse than a line in the console.
  const extraActions = actions.length - MAX_ACTIONS;
  React.useEffect(() => {
    if (extraActions > 0) {
      console.warn(
        `[@bisheng/ui] Alert takes at most ${MAX_ACTIONS} actions (Alert spec, section 5.3); ignoring ${extraActions} extra.`,
      );
    }
  }, [extraActions]);

  if (dismissed) {
    return null;
  }

  const visibleActions = actions.slice(0, MAX_ACTIONS);
  // A title always stacks: the body sits on its own line underneath it (§4).
  const stacked = Boolean(title) || flags.wrapped;
  // Icon, actions and close ride the FIRST text line once the box stacks —
  // a one-line-tall box centres them on it (§4).
  const firstLine = stacked ? 'h-[var(--leading-body)] items-center self-start' : undefined;

  return (
    <div
      className={cn(
        // §6: the wrapper collapses its own height AND its vertical margin, so
        // the content below slides up in 200ms instead of jumping.
        'mx-2 grid transition-[grid-template-rows,margin-top,margin-bottom] duration-200',
        EASE,
        closing ? 'my-0 grid-rows-[0fr]' : 'my-2 grid-rows-[1fr]',
        className,
      )}
    >
      {/* The 0fr collapse only bites when the row clips its content, but a box
          that fits the alert exactly also cuts the buttons' focus ring. So clip
          only while collapsing — by then it has faded out anyway. */}
      <div className={closing ? 'overflow-hidden' : undefined}>
        <div
          // §8: no live region unless the alert was inserted in reaction to the
          // user; focus is never moved here either way.
          role={live ? (meta.assertive ? 'alert' : 'status') : undefined}
          className={cn(
            // §4: 16px sides, 12px radius, tinted surface, no border, no shadow.
            'flex rounded-xl px-4 transition-opacity duration-200',
            meta.surface,
            EASE,
            // §4: exactly 40px with no vertical padding while it is one line.
            stacked ? 'items-start py-3' : 'h-10 items-center',
            closing && 'opacity-0',
          )}
        >
          {/* Decorative — §8: the copy carries the meaning, so the icon is not
              announced. Always 16px, never scaled by the presence of a title. */}
          <span className={cn('flex shrink-0', firstLine)}>
            <Icon aria-hidden className={cn('size-4', meta.iconColor)} />
          </span>

          <div ref={textRef} className="ml-2 min-w-0 flex-1">
            {title ? (
              // §5.1: one line, ellipsis past it. The native tooltip is only
              // attached when something is actually cut off.
              <div
                ref={titleRef}
                className="line-clamp-1 text-body font-medium text-text-1"
                title={flags.titleClipped ? title : undefined}
              >
                {title}
              </div>
            ) : null}
            {/* §4: 主文字色 on its own, 次要文字色 under a title — never the
                semantic color, which the icon and the tint already say and
                which does not have the contrast for a whole sentence here. */}
            <p
              ref={descriptionRef}
              className={cn(
                'line-clamp-2 break-words text-body',
                title ? 'mt-1 text-text-2' : 'text-text-1',
              )}
              title={flags.descriptionClipped ? description : undefined}
            >
              {description}
            </p>
          </div>

          {visibleActions.length > 0 ? (
            // §5.3: pinned right, 24px borderless buttons — a filled one would
            // put a second block of color on a tinted surface and turn the
            // alert into a card. The primary one comes first, which keeps it
            // away from the close button it must not be confused with.
            //
            // `link`, not the `text` the spec names (deviation, §10): `text`
            // says hover = a light fill, and primary × text fills with
            // `bg-blue-50` — the exact surface an info alert already has, so
            // the hover would be invisible there and a blue block on the other
            // three tints. `link` darkens and underlines instead, which is
            // also what the landed Toast action does on the same geometry.
            // px-0 keeps §4's gaps exact: 16px from the copy, 8px between.
            <div className={cn('ml-4 flex shrink-0 items-center gap-2', firstLine)}>
              {visibleActions.map((action, index) => (
                <Button
                  key={action.label}
                  color={index === 0 ? 'primary' : 'default'}
                  variant="link"
                  size="small"
                  className="btn-touch-hit px-0"
                  onClick={action.onClick}
                >
                  {action.label}
                </Button>
              ))}
            </div>
          ) : null}

          {closable ? (
            // §4: a bare 16px glyph flush against the 16px padding, faint
            // until hovered — it is an escape hatch, not something to look at.
            // `btn-touch-hit` gives it the 44px hot zone without growing it.
            <button
              type="button"
              aria-label={closeLabel}
              className={cn(
                'btn-touch-hit relative ml-4 flex shrink-0 text-text-4 transition-colors hover:text-text-2',
                firstLine,
              )}
              onClick={() => setClosing(true)}
            >
              <Outlined.Close aria-hidden className="size-4" />
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
