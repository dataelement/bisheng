import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Tooltip } from '../Tooltip';

/**
 * Tag — design-system base component (组件-Tag标签.md v1).
 *
 * A tag puts ONE word on an object: what it is, what state it is in, which
 * category it belongs to (§1). It labels an attribute, never an action — a
 * tag looks clickable, so a display tag deliberately has no hover at all
 * (§6); lighting up and then doing nothing is a lie told once per tag. What
 * says「how many / anything new」is a Badge (判别表 in 组件-Badge徽标.md §1).
 *
 * One look only: a light tint with dark text, 4px radius, no border, no solid
 * fill, no gray outline variant (§2) — the designer's call, and adding one
 * back is a spec change, not a prop.
 *
 * Two axes that pick independently (§3): a semantic color (what is being
 * said) × an interaction type (what it can do). Semantic colors carry the
 * meaning — the same state is the same color across the whole product — and
 * the two frozen exceptions,「审批中」blue and「技能」purple, are their own
 * colors here because they must NOT follow the blue⇄green theme switch
 * (色彩规范 §4). There is no eighth color: a category with no meaning is
 * `default` gray, or the reader is left guessing whether blue outranks green.
 *
 * The status form lives here too (moved from Badge 2026-08-28): `dot` puts a
 * small filled circle in front of the word, in the tag's own color. A list row
 * that reports 「解析失败」 is saying WHAT this file is right now — an
 * attribute — so it is a tag, not a badge; the badge only ever answers 「is
 * there anything new / how many」 (判别表 in 组件-Badge徽标.md §1).
 *
 * Baked in per spec: the 20/24 size ladder at 12/400 (a tag is one rung below
 * the control it is stuck on, §4); a checkable tag always starts gray and
 * turns brand-tinted when checked, so selection owns the color channel and
 * cannot be combined with a semantic one (§3.2); removal is immediate with no
 * confirm — re-picking is the undo (§3.2); an avatar turns the tag into a
 * pill, because a square corner around a round face reads as a rendering bug
 * (§5); `maxWidth` truncates and only then mounts a Tooltip (§5); ≥44px touch
 * hot zones, and a checkable tag jumps to medium on touch where 20px is
 * unhittable (§7).
 */

/** §4 — two rungs. `medium` is the default; `small` is for a table cell, a
 * list row, or the picked items inside a 32px field. */
export type TagSize = 'small' | 'medium';

/**
 * §3.1 — five semantic colors plus the three frozen exceptions. `approving`,
 * `skill` and `web` are separate values rather than `brand`: they are pinned
 * to blue and purple in BOTH brand themes (色彩规范 §4), which is exactly what
 * `brand` cannot promise. `web` is the same purple as `skill` under its own
 * use-name — it labels a web source, and it has to match the citation badge
 * marking that same source in the answer (组件-Badge徽标.md §2).
 */
export type TagColor =
  | 'default'
  | 'brand'
  | 'success'
  | 'warning'
  | 'danger'
  | 'approving'
  | 'skill'
  | 'web';

/** §3.1 — tint background + main-color text, both from the token layer, so
 * dark mode arrives on its own (the dark tints are deep saturated washes, not
 * light chips — 色彩规范 §3). */
const COLOR: Record<TagColor, string> = {
  default: 'bg-fill-2 text-text-2',
  brand: 'bg-blue-50 text-blue-500',
  success: 'bg-success-tint text-success',
  warning: 'bg-warning-tint text-warning',
  danger: 'bg-danger-tint text-danger',
  approving: 'bg-tag-approving-tint text-tag-approving',
  skill: 'bg-tag-skill-tint text-tag-skill',
  web: 'bg-citation-web-tint text-citation-web',
};

/** §6 — one disabled look for every color: the tag is still there, it just
 * stops claiming anything. */
const DISABLED = 'bg-fill-1 text-text-4';

/** §4 — height, horizontal padding, icon rung. Font is `text-caption` (12/20)
 * on both rungs; the height is what changes, not the type.
 *
 * `[&>svg]`, NOT `[&_svg]`: the leading icon rides the 12/14 rung, but the
 * close 「×」 is fixed at 12px on both rungs (§5), and it is nested inside its
 * own button. A descendant selector here would out-specify the 「×」's own
 * `size-3` (0,2,0 beats 0,1,0) and silently blow it up to 14px on the medium
 * rung — which is exactly what it did until this was scoped to direct
 * children. */
const SIZE: Record<TagSize, string> = {
  small: 'h-5 gap-1 px-1.5 [&>svg]:size-3',
  medium: 'h-6 gap-1 px-2 [&>svg]:size-3.5',
};

/** §5 — the status dot rides the same ladder as the icon it replaces: 4px on
 * the 20px rung (what the knowledge-space file list draws today), 6px on the
 * 24px one. It takes the tag's own text color (`currentColor`), so a status
 * never needs a second color decision — `color="danger"` makes both the word
 * and the dot red. */
const DOT_SIZE: Record<TagSize, string> = {
  small: 'size-1',
  medium: 'size-1.5',
};

/** §5 — the avatar is 14/16px and sits flush, so THAT side's padding drops to
 * 4px. The 「×」 side does not: see the shell below. */
const AVATAR_SIZE: Record<TagSize, string> = {
  small: 'size-3.5',
  medium: 'size-4',
};

export interface TagProps {
  /** The word itself: 2–6 chars, a noun or a state, no punctuation and no
   * verb (§5). Comes from the caller — the library holds no copy. */
  children: React.ReactNode;
  /** §4 — default `medium` (24px). One group of tags uses ONE rung. */
  size?: TagSize;
  /** §3.1 — default `default` (gray). One meaning keeps one color product-wide. */
  color?: TagColor;
  /**
   * §5 — a filled dot in front of the word, in the tag's own color: the form a
   * list row uses to report state (「运行中」/「失败」) when every row carries
   * one and the eye has to scan the column. Wins over `icon`; ignored when
   * `avatar` is set. NO pulse animation, ever — a column of breathing dots is
   * a column nobody can read.
   */
  dot?: boolean;
  /** §5 — leading icon, 12/14px, inherits the text color. Either all the tags
   * in a group have one or none do. Ignored when `dot` or `avatar` is set. */
  icon?: React.ReactNode;
  /** §5 — leading avatar (14/16px, cropped to a circle here). Turns the tag
   * into a pill and forces the gray `default` color: a face plus a semantic
   * tint is two claims in one chip. */
  avatar?: React.ReactNode;
  /**
   * §3.2 — the「×」that removes this tag. Removal is immediate and needs no
   * confirm; deleting the underlying THING is a button with a real confirm.
   * Ignored on a checkable tag — a button inside a button is invalid HTML,
   * and「pick it / drop it」are two answers to the same question anyway.
   */
  closable?: boolean;
  onClose?: (event: React.MouseEvent<HTMLButtonElement>) => void;
  /** Accessible name of the「×」. Text comes from the caller (library contract). */
  closeLabel?: string;
  /** §3.2 — click to toggle. Always starts from the gray fill; `color` is
   * ignored, because the checked state already owns the color channel. */
  checkable?: boolean;
  /** Controlled checked state; use `defaultChecked` for uncontrolled. */
  checked?: boolean;
  defaultChecked?: boolean;
  onChange?: (checked: boolean) => void;
  /**
   * §5 — cap the width in px: the label truncates and a Tooltip with the full
   * text appears, but ONLY once it actually overflows. For fixed-width columns;
   * everywhere else let the tag be as wide as its word.
   */
  maxWidth?: number;
  /** §6 — display and closable tags grey out; a checkable one also stops toggling. */
  disabled?: boolean;
  className?: string;
}

function Tag({
  children,
  size = 'medium',
  color = 'default',
  dot = false,
  icon,
  avatar,
  closable = false,
  onClose,
  closeLabel = 'Remove',
  checkable = false,
  checked,
  defaultChecked = false,
  onChange,
  maxWidth,
  disabled = false,
  className,
}: TagProps) {
  const [innerChecked, setInnerChecked] = React.useState(defaultChecked);
  const isChecked = checked !== undefined ? checked : innerChecked;

  // §5 — mount the Tooltip only for a label that is really clipped: one
  // hover listener per tag in a filter panel is a lot of listeners for a
  // tooltip that would never say anything new.
  const labelRef = React.useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = React.useState(false);
  React.useLayoutEffect(() => {
    const label = labelRef.current;
    if (maxWidth === undefined || !label) {
      setOverflowing(false);
      return;
    }
    const measure = () => setOverflowing(label.scrollWidth > label.clientWidth + 1);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(label);
    return () => ro.disconnect();
  }, [maxWidth, children]);

  const handleToggle = () => {
    const next = !isChecked;
    setInnerChecked(next);
    onChange?.(next);
  };

  const withAvatar = avatar !== undefined;
  const showClose = closable && !checkable;

  const fill = disabled
    ? // §6 — a checked-but-disabled tag keeps the brand text so the user can
      // still read WHICH ones are picked; only the fill drops out.
      checkable && isChecked
      ? 'bg-text-4/20 text-blue-500'
      : DISABLED
    : checkable
      ? isChecked
        ? // §6 — the 7% brand tint the whole product uses for「selected」
          // (色彩规范 §1.2), 10% on hover.
          'bg-blue-500/[0.07] text-blue-500 hover:bg-blue-500/10'
        : 'bg-fill-2 text-text-2 hover:bg-fill-3'
      : COLOR[withAvatar ? 'default' : color];

  const body = (
    <>
      {withAvatar ? (
        <span
          aria-hidden
          className={cn('shrink-0 overflow-hidden rounded-full [&>*]:size-full', AVATAR_SIZE[size])}
        >
          {avatar}
        </span>
      ) : dot ? (
        // The word next to it is the content; the dot is a color cue, so it is
        // decorative to a screen reader.
        <span aria-hidden className={cn('shrink-0 rounded-full bg-current', DOT_SIZE[size])} />
      ) : (
        icon
      )}
      <span
        ref={labelRef}
        className={cn('min-w-0', maxWidth !== undefined && 'truncate')}
        style={maxWidth !== undefined ? { maxWidth } : undefined}
      >
        {children}
      </span>
      {showClose && (
        <button
          type="button"
          aria-label={closeLabel}
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation();
            onClose?.(event);
          }}
          className={cn(
            // §5 — the hot zone is the tag's full height; the icon is 12px on
            // both rungs. §6 — only the × reacts to hover, never the tag body.
            'btn-touch-hit relative inline-flex h-full shrink-0 items-center rounded-sm outline-none',
            'text-text-3 transition-colors hover:text-text-1 focus-visible:shadow-focus',
            'disabled:cursor-not-allowed disabled:text-text-4 disabled:hover:text-text-4',
          )}
        >
          <Outlined.Close className="size-3" />
        </button>
      )}
    </>
  );

  const shell = cn(
    // §2 — 4px radius, one line, centered; the label is the only thing allowed
    // to shrink (min-w-0 on it) so an icon or the × never gets squeezed out.
    'inline-flex max-w-full items-center rounded-sm text-caption font-normal align-middle',
    SIZE[size],
    // §5 — a face is round, so the chip becomes a pill and hugs it at 4px.
    withAvatar && 'rounded-full pl-1',
    // §5 (2026-08-28) — the 「×」 side keeps the rung's own padding (8px on
    // medium, 6px on small). It used to shrink to 4px the way the avatar side
    // does; on screen that read as the 「×」 falling out of the chip, because
    // unlike an avatar the icon has no fill of its own to hold the edge.
    fill,
    className,
  );

  const tag = checkable ? (
    <button
      type="button"
      aria-pressed={isChecked}
      disabled={disabled}
      onClick={handleToggle}
      className={cn(
        shell,
        // §7 — 20px is not a touch target: a checkable tag takes the medium
        // rung on touch, on top of the invisible ≥44px hot zone every
        // interactive control gets.
        'btn-touch-hit relative cursor-pointer outline-none transition-colors focus-visible:shadow-focus',
        'coarse-pointer:h-6 coarse-pointer:px-2',
        'disabled:cursor-not-allowed',
      )}
    >
      {body}
    </button>
  ) : (
    <span className={shell}>{body}</span>
  );

  // §5 — same overflow rule as everywhere else: truncate, then let a hover
  // reveal the full text.
  if (maxWidth === undefined) return tag;
  return (
    <Tooltip content={children} disabled={!overflowing}>
      {tag}
    </Tooltip>
  );
}

export { Tag };
