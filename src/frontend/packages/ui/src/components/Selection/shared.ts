/**
 * Shared internals of the selection family — Checkbox / Radio (组件-Checkbox复选框.md
 * / 组件-Radio单选框.md, both v1).
 *
 * The two specs share one ladder (§3: control 14/16/18, text 14/14/16, 8px gap),
 * one state chain (§5: gray ramp until checked, brand at the moment of choice,
 * the button's three disabled tokens) and one card shell (Checkbox §2, adopted
 * by Radio §2), so the classes live once here. Internal module — not exported
 * from the package entry.
 */

/** §3 — same small/medium/large ladder as Button / Input. */
export type SelectionSize = 'small' | 'medium' | 'large';

/**
 * Row text sizes reference the PRIMITIVE type vars on purpose: the semantic
 * --text-body remaps 14→16 under 768px for reading text, while control rows
 * keep the §3 ladder so the box stays aligned with its first line.
 */
export const ROW_TEXT: Record<SelectionSize, string> = {
  small: 'text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  medium: 'text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  large: 'text-[length:var(--font-size-4)] leading-[var(--line-height-4)]',
};

/** Centers the control on the label's FIRST line: (line-height − control) / 2. */
export const CONTROL_OFFSET: Record<SelectionSize, string> = {
  small: 'mt-1', // (22 − 14) / 2
  medium: 'mt-[3px]', // (22 − 16) / 2
  large: 'mt-[3px]', // (24 − 18) / 2
};

/** §3 — control square/circle 14/16/18 with the matching indicator-icon size. */
export const CONTROL_SIZE: Record<SelectionSize, string> = {
  small: 'size-3.5 [&_svg]:size-2.5',
  medium: 'size-4 [&_svg]:size-3',
  large: 'size-[18px] [&_svg]:size-3.5',
};

/**
 * §4/§6 — the whole row is the hot zone (text included), disabled turns the
 * row text gray with the not-allowed cursor (§5's three signals), and touch
 * pads the row to ≥44px ("整行 label 撑高", 落地 note).
 */
export const ROW_BASE =
  'group/row inline-flex max-w-full cursor-pointer items-start gap-2 text-text-1 coarse-pointer:py-[11px] has-[[data-disabled]]:cursor-not-allowed has-[[data-disabled]]:text-btn-disabled-text';

/** Hovering anywhere on the row deepens an UNCHECKED control's border (§5). */
export const ROW_HOVER_CONTROL = 'group-hover/row:data-[state=unchecked]:border-border-deep';

/** §4 — one secondary line, hint color; goes disabled-gray with the row. */
export const DESCRIPTION = 'text-text-3 group-has-[[data-disabled]]/row:text-btn-disabled-text';

/**
 * §5 — the state chain both controls share. Unchecked: page bg + base border,
 * hover deepens the border only. Disabled: the button's three tokens with `!`
 * so they beat the checked brand color (same technique as Button). Focus ring
 * appears on :focus-visible only — keyboard, not click.
 */
export const CONTROL_BASE =
  'btn-touch-hit relative inline-flex shrink-0 cursor-pointer items-center justify-center border border-border-base bg-bg-page outline-none transition-colors hover:data-[state=unchecked]:border-border-deep focus-visible:shadow-focus disabled:cursor-not-allowed disabled:!border-btn-disabled-border disabled:!bg-btn-disabled-bg disabled:!text-btn-disabled-text';

/**
 * §5 — checked is the semantic moment: brand fill (follows blue⇄green), white
 * mark. The mark draws with currentColor, so the disabled override above also
 * grays it (选中禁用 = 浅灰底 + 灰勾/灰点).
 */
export const CONTROL_CHECKED =
  'data-[state=checked]:border-blue-500 data-[state=checked]:bg-blue-500 data-[state=checked]:text-white';

/** §2 — group spacing: horizontal 16, vertical 8; narrow screens always stack. */
export const GROUP_LAYOUT: Record<'horizontal' | 'vertical', string> = {
  horizontal: 'flex flex-wrap gap-x-4 gap-y-2 max-[768px]:flex-col',
  vertical: 'flex flex-col gap-2',
};

/**
 * Checkbox §2 (adopted by Radio §2) — the card shell: radius 12 / min-height 48
 * / 12px horizontal padding; hover is a light gray wash; selection tints the
 * WHOLE card with the unified selection bg AND turns the border a light brand
 * step (blue-100, follows the theme) — the original keep-it-gray route read
 * mismatched against the brand tint (designer call, 2026-08-25); disabled
 * reuses the row's three signals with the hover wash suppressed.
 */
export const CARD_SHELL =
  'group/row flex min-h-12 cursor-pointer items-center gap-2 rounded-xl border border-border-base px-3 text-body text-text-1 transition-colors hover:bg-fill-1 has-[[data-state=checked]]:border-blue-100 has-[[data-state=checked]]:bg-blue-500/[0.07] has-[[data-disabled]]:cursor-not-allowed has-[[data-disabled]]:text-btn-disabled-text has-[[data-disabled]]:hover:bg-transparent';

/** Card title: medium weight, body color (§2). */
export const CARD_LABEL = 'shrink-0 whitespace-nowrap font-medium';

/** Card secondary line: hint color, ellipsis when it runs out of room (§2). */
export const CARD_DESCRIPTION =
  'min-w-0 truncate text-text-3 group-has-[[data-disabled]]/row:text-btn-disabled-text';

/**
 * Focus ring, INSET flavor — the segmented radio-button group clips children
 * (overflow-hidden keeps cell corners inside the shared border), so the same
 * 2px token ring draws inward. Same focus-indicator exception as
 * `shadow-focus` (design-token FOCUS_RING) — the color IS the token var.
 */
export const FOCUS_RING_INSET =
  'focus-visible:shadow-[inset_0_0_0_2px_rgb(var(--shadow-focus-ring))]';
