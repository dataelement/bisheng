import * as React from 'react';
import cn from '../../utils/cn';

/**
 * Badge — design-system base component (组件-Badge徽标.md v1).
 *
 * A badge answers two questions only: IS there anything new, and HOW MANY
 * (§1). It carries no content of its own, it is never a button, and a red dot
 * that never clears is the same as no red dot at all. What says「what this
 * is」is a Tag (判别表 in §1 of the same doc).
 *
 * Five forms, one size — the badge does not grow with its host (§3):
 *   • `count` on a host      — 16px pill in the host's top-right corner (§2)
 *   • `dot` on a host        — 6px circle, same corner (§2)
 *   • `count` with no host   — the standalone number after a tab / menu label
 *   • `dot` with no host     — the unread marker in its own column of a list row
 *   • `citation`             — the 溯源角标 inside running text: the ordinal of
 *                              a source, and the ONE form that is clickable
 *                              (§5, added 2026-08-28)
 *
 * Reporting a STATE (「运行中」/「失败」) is not one of them: that is a dot
 * plus a word, which is a word about the object — a Tag with `dot` (§1, moved
 * there 2026-08-28).
 *
 * Baked in per spec: two semantic colors — `danger` solid (「needs you」, the
 * corner default) and `brand` 5% tint (「just how many」, the standalone
 * default) — and they are not interchangeable (§2); the number is NEVER
 * abbreviated (no 99+) and the pill widens with the digits (§3); tabular
 * figures so 9→10 does not jitter (§3); a 1px page-colored ring so a corner
 * badge stays legible on a colored icon or an avatar (§3); 0 renders nothing
 * unless the caller opts in with `showZero` (§4); no hover, no focus, no
 * click, no enter/leave transition — the click belongs to the host (§5). The
 * citation form is the single exception to that last rule, because a footnote
 * marker IS the link to its source; it is a real `<button>` and forwards its
 * ref, so a Popover trigger can drive it (§5).
 *
 * The corner form is decorative to a screen reader (`aria-hidden`): the host
 * carries the merged description (`aria-label="通知，3 条未读"`, §落地 4).
 */

/** §2 — semantic, not positional: red = act on it, brand tint = just a count. */
export type BadgeColor = 'danger' | 'brand';

/** §2 — where the cited source came from. Two colors, so a reader can tell a
 * document from a web page without opening either. */
export type BadgeCitationSource = 'document' | 'web';

/**
 * §2 — `danger` is a solid fill with white text (the loudest thing on the
 * page, reserved for「waiting on you」); `brand` is the 5% brand tint drawn
 * by Tabs today, so it follows the blue⇄green theme and the dark brand ramp
 * with no `dark:` override.
 */
const COLOR: Record<BadgeColor, string> = {
  danger: 'bg-danger text-white',
  brand: 'bg-blue-500/5 text-blue-500',
};

/** §5 — a dead entry's badge greys out with it; nagging about something the
 * user cannot act on is worse than saying nothing. */
const DISABLED_FILL = 'bg-text-4 text-white';

/**
 * §2 — the citation badge's two source colors. Both are a FULL light tint, not
 * the standalone number's 5% wash: this one sits inside a paragraph of running
 * text, where a 5% wash reads as a printing flaw rather than a marker.
 *
 * `document` rides the brand ramp (`blue-*` is the brand ramp here), so it
 * follows the blue⇄green theme like everything else. `web` is frozen — the
 * system's one purple, which belongs to no theme (基础-色彩规范 §4).
 */
const CITATION: Record<BadgeCitationSource, string> = {
  document: 'bg-blue-50 text-blue-600 hover:bg-blue-100 data-[state=open]:bg-blue-100 focus-visible:ring-blue-600/25',
  web: 'bg-citation-web-tint text-citation-web hover:bg-citation-web/15 data-[state=open]:bg-citation-web/15 focus-visible:ring-citation-web/25',
};


/** §3 — one size, 16px tall, min 16px wide, full radius (a single digit is a
 * circle, two digits stretch it into a pill), the
 * caption-sm rung the type scale keeps for exactly this, weight 500, tabular
 * figures. `leading-none` because the 18px line box of caption-sm would
 * otherwise fight the 16px height. */
const PILL =
  'inline-flex h-4 min-w-4 items-center justify-center px-1 text-caption-sm font-medium leading-none tabular-nums';

/** §3 — 6px circle. */
const DOT = 'inline-block h-1.5 w-1.5 shrink-0 rounded-full';

export interface BadgeProps extends Omit<React.HTMLAttributes<HTMLElement>, 'color' | 'children'> {
  /**
   * The host the badge rides on — an icon, an avatar, a nav entry. WITH a
   * host the badge is a corner badge; WITHOUT one it is the standalone number.
   * The shape of the call site decides, so there is nothing to declare —
   * except in the `citation` form, where there is no host and `children` is
   * the ordinal itself.
   */
  children?: React.ReactNode;
  /**
   * How many. Rendered as given — never abbreviated, never capped (§3): a
   * four-digit unread count is a notification-policy problem, not a badge
   * problem. 0 and `undefined` render nothing (§4), so a caller can pass a
   * raw count straight through without guarding it.
   */
  count?: number;
  /**
   * §2 — 「there is something new」 without a number. On a host it rides the
   * top-right corner; with no host it is the unread marker a list row keeps in
   * its own column. Ignored when `count` shows.
   */
  dot?: boolean;
  /**
   * §2 — defaults by position, because the two forms mean different things:
   * a corner badge is `danger` (act on it), a standalone number is `brand`
   * (just how many). Override when the host component has its own palette —
   * a neutral Tabs row passes its own classes via `className`.
   */
  color?: BadgeColor;
  /** §4 — render `0` instead of nothing. Only for「0 is itself the answer」
   * (a filter result count); an unread counter must stay silent at zero. */
  showZero?: boolean;
  /** §5 — the host is round (avatar, circular icon button), so pull the badge
   * in until its center sits ON the circumference instead of off in space. */
  circle?: boolean;
  /** §5 — `[x, y]` px nudge of the corner badge, for hosts whose artwork does
   * not fill its box. Positive x moves right, positive y moves down. */
  offset?: [number, number];
  /** §5 — grey out with a disabled host. */
  disabled?: boolean;
  /**
   * §5 — the 溯源角标: renders a `<button>` carrying `children` (the source's
   * ordinal) and nothing else. The only interactive form — the marker IS the
   * link to its source — so the call site owns the behaviour (`onClick`, the
   * hover card, `data-state` while the popover is open) and passes it through
   * like any DOM prop. Every other form ignores the click: it belongs to the
   * host.
   */
  citation?: BadgeCitationSource;
  /** Classes for the OUTER element: the wrapper in corner mode, the badge
   * itself otherwise. */
  className?: string;
  /** Classes for the badge itself, in every mode. */
  badgeClassName?: string;
}

const Badge = React.forwardRef<HTMLElement, BadgeProps>(function Badge({
  children,
  count,
  dot = false,
  color,
  showZero = false,
  circle = false,
  offset,
  disabled = false,
  citation,
  className,
  badgeClassName,
  ...rest
}, ref) {
  if (citation) {
    return (
      <button
        ref={ref as React.Ref<HTMLButtonElement>}
        type="button"
        {...rest}
        className={cn(
          PILL,
          // §5 — center the marker on the line it annotates. Two steps, and
          // both are needed:
          //   `align-middle` — an inline box sits on the BASELINE by default,
          //     which drops a 16px circle to the descender line.
          //   `-top-[0.16em]` — `middle` is defined as「baseline + half the
          //     x-height」, and a Chinese glyph stands taller than the Latin
          //     x-height, so the marker still hangs ~0.11em of the TEXT's size
          //     low. 0.16em of the badge's own 10px ≈ 1.6px, which is that
          //     gap for both body rungs (14px desktop / 16px mobile) to within
          //     0.2px. Relative offset, so the line box does not move.
          'relative -top-[0.16em] cursor-pointer select-none rounded-full align-middle outline-none transition-colors duration-150 focus-visible:ring-2',
          CITATION[citation],
          className,
          badgeClassName,
        )}
      >
        {children ?? count}
      </button>
    );
  }

  const hasHost = children !== undefined;
  // §4 — 0 is silence unless the caller says 0 is the answer.
  const showCount = count !== undefined && (count > 0 || (showZero && count === 0));
  const showDot = !showCount && dot;
  // §2 — the default is per FORM, not per position: a dot always means
  // 「something new」 and is therefore always red; only the standalone NUMBER
  // defaults to the quiet brand tint, because that one is just reporting how
  // many. (A brand-tinted dot would be a 5% wash 6px across — invisible.)
  const fill = disabled ? DISABLED_FILL : COLOR[color ?? (hasHost || showDot ? 'danger' : 'brand')];

  if (!hasHost) {
    // §3 (2026-08-28) — the standalone number is the SAME pill as the corner
    // one: full radius, so a single digit is a circle. It shipped at the 6px
    // radius Tabs had been drawing; the designer settled the open question on
    // the settings nav — one number badge, one radius.
    if (showCount) {
      return (
        <span ref={ref as React.Ref<HTMLSpanElement>} {...rest} className={cn(PILL, 'rounded-full', fill, className, badgeClassName)}>
          {count}
        </span>
      );
    }
    // §2 — the same red dot, in its own column: a list row whose unread marker
    // has nowhere to hang (no icon, no avatar) still needs one, and the row is
    // the host in every sense that matters. No page-colored ring here — there
    // is nothing underneath it to separate from.
    if (showDot) {
      return <span ref={ref as React.Ref<HTMLSpanElement>} aria-hidden {...rest} className={cn(DOT, fill, className, badgeClassName)} />;
    }
    return null;
  }

  const [dx, dy] = offset ?? [0, 0];
  // §5 — the badge's CENTER lands on the host's top-right corner; on a round
  // host it is pulled in by 14.6% of the box (cos45°/2) so the center lands on
  // the circumference instead. `transform` owns both halves of the placement,
  // so an `offset` cannot fight a translate utility.
  const inset = circle ? '14.6%' : '0';

  return (
    <span ref={ref as React.Ref<HTMLSpanElement>} {...rest} className={cn('relative inline-flex', className)}>
      {children}
      {(showCount || showDot) && (
        <span
          aria-hidden
          className={cn(
            'absolute',
            // §3 — a 1px ring in the page color separates the badge from a
            // colored icon or a photo underneath; it follows the theme, so
            // dark mode needs no override.
            'ring-1 ring-bg-page',
            showCount ? cn(PILL, 'rounded-full') : DOT,
            fill,
            badgeClassName,
          )}
          style={{
            top: inset,
            right: inset,
            transform: `translate(calc(50% + ${dx}px), calc(-50% + ${dy}px))`,
          }}
        >
          {showCount ? count : null}
        </span>
      )}
    </span>
  );
});

export { Badge };
