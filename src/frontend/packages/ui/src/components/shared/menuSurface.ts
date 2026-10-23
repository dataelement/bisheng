import cn from '../../utils/cn';

/**
 * The floating panel Select and Dropdown share (组件-Select选择器.md §5, which
 * 组件-Dropdown下拉菜单.md §4 references instead of restating). One file so the
 * two components cannot drift apart: the shell, the 32px row, the group label,
 * the separator, the empty line and the radius ladder are all defined here.
 */

/**
 * The radius ladder (design-token.cjs RADIUS, 基础-圆角与阴影规范.mdx §1.1).
 * Spelled out rather than derived with `typeof RADIUS[number]['name']`: the
 * token file is plain CommonJS, which this strict TS package does not type-check,
 * and a JS array literal would only infer `string` anyway. The `Record` maps
 * below are exhaustive over this union, so adding a rung there without adding
 * it here (or the other way round) fails `pnpm typecheck`.
 */
export type RadiusToken = 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl' | '4xl' | 'full';

/** §5.4 — a panel is a surface, so it never becomes a pill. */
export type PanelRadius = Exclude<RadiusToken, 'full'>;

/** Token → class. Only rungs of the ladder exist; there is no free-form radius. */
export const RADIUS_CLASS: Record<RadiusToken, string> = {
  sm: 'rounded-sm',
  md: 'rounded-md',
  lg: 'rounded-lg',
  xl: 'rounded-xl',
  '2xl': 'rounded-2xl',
  '3xl': 'rounded-3xl',
  '4xl': 'rounded-4xl',
  full: 'rounded-full',
};

/**
 * §5.4 — the row radius follows the panel so the arcs stay concentric: panel
 * minus the 6px padding, rounded DOWN to the nearest rung, never below `sm`.
 * Not configurable on its own — a row that disagrees with its panel leaves a
 * gap that is wide at one end and narrow at the other.
 */
export const OPTION_RADIUS_CLASS: Record<PanelRadius, string> = {
  sm: 'rounded-sm',
  md: 'rounded-sm',
  lg: 'rounded-sm',
  xl: 'rounded-md',
  '2xl': 'rounded-lg',
  '3xl': 'rounded-2xl',
  '4xl': 'rounded-3xl',
};

export const DEFAULT_PANEL_RADIUS: PanelRadius = 'xl';

/** §5.1 — 4px between trigger and panel. */
export const PANEL_SIDE_OFFSET = 4;

/** Dropdown 落地 §2 — keep 8px from the viewport edge when flipping / shifting. */
export const PANEL_COLLISION_PADDING = 8;

/**
 * §8 — fade in 150ms while sliding 4px in from the trigger's side, fade out
 * 100ms (the Tooltip pair of durations). The `data-[state=open]` guard keeps
 * the entry animations from competing with the exit one on the same element.
 */
const PANEL_MOTION =
  'data-[state=open]:data-[side=bottom]:animate-popup-in-down ' +
  'data-[state=open]:data-[side=top]:animate-popup-in-up ' +
  'data-[state=open]:data-[side=right]:animate-popup-in-right ' +
  'data-[state=open]:data-[side=left]:animate-popup-in-left ' +
  'data-[state=closed]:animate-popup-out data-[state=closed]:[animation-fill-mode:forwards] ' +
  'motion-reduce:animate-none';

/**
 * The vertical rhythm inside a menu column: 4px between any two children —
 * rows, group labels, separators. `shrink-0` on the children matters: in a
 * flex column the items shrink BEFORE the container scrolls, which would
 * collapse the separator's 1px line and squash group labels on overflow.
 */
export const MENU_STACK = 'flex flex-col gap-1 [&>*]:shrink-0';

/**
 * The scrollable contents of one menu column: Select has one, Cascader has
 * one per visible level. Keeping the padding, the 4px row gap and the
 * eight-row limit here makes a one-column Cascader pixel-identical to Select.
 */
export const MENU_COLUMN = cn(
  MENU_STACK,
  'max-h-[296px] overflow-y-auto overscroll-contain p-1.5',
);

/**
 * §5.1 — page-colored surface separated by the popup shadow, 6px padding (so
 * an option's text starts 12px in — level with a medium trigger's text), at
 * most 8 rows (8 × 32 + 7 × 4 gaps + 6 + 6 = 296px) before it scrolls, on
 * the popover tier.
 *
 * §10 — in dark mode the shadow is only a dim halo on a page of the same color,
 * so a 1px neutral outline marks the edge (same as Notification).
 *
 * The shared floating surface without an opinion about its inner columns.
 */
export function panelSurfaceClass(radius: PanelRadius, className?: string): string {
  return cn(
    'z-popover bg-bg-page text-text-1 shadow-popup outline-none',
    'dark:border dark:border-border-base',
    RADIUS_CLASS[radius],
    PANEL_MOTION,
    className,
  );
}

export function panelClass(radius: PanelRadius, className?: string): string {
  return panelSurfaceClass(radius, cn(MENU_COLUMN, className));
}

/**
 * §5.2 / §7.2 — one 32px row: 14/22 text (the PRIMITIVE scale — the semantic
 * body size remaps to 16 under 768px for reading text, which a control must
 * not follow), 6px side padding, gray `fill-2` for both hover and the keyboard
 * highlight (the same look on purpose), disabled in `text-4` with the "not
 * allowed" cursor. A one-line description makes the row grow: 5px top/bottom.
 *
 * State is read from `data-highlighted` / `data-disabled`, which Radix sets on
 * menu items and the Select listbox sets on its own options.
 */
export function optionClass(radius: PanelRadius, className?: string): string {
  return cn(
    'relative flex min-h-8 w-full cursor-pointer select-none items-center gap-2 px-1.5 py-[5px]',
    'text-[length:var(--font-size-3)] leading-[var(--line-height-3)] text-text-1 outline-none transition-colors',
    'data-[highlighted]:bg-fill-2',
    'data-[disabled]:cursor-not-allowed data-[disabled]:text-text-4 data-[disabled]:data-[highlighted]:bg-transparent',
    OPTION_RADIUS_CLASS[radius],
    className,
  );
}

/** §5.2 — the 16px leading icon, 8px from the text (the row's own gap). */
export const OPTION_ICON = 'flex size-4 shrink-0 items-center justify-center [&>svg]:size-4';

/** §5.2 — the one-line description under a label: 12/20 hint gray, 2px below. */
export const OPTION_DESCRIPTION =
  'mt-0.5 truncate text-[length:var(--font-size-1)] leading-[var(--line-height-1)] text-text-3';

/** §7.2 — the selected check: 16px, brand, at the right end of the row. */
export const OPTION_CHECK = 'ml-auto size-4 shrink-0 text-blue-500';

/** §5.3 — group title: 12/20 hint gray, 4px top/bottom, never selectable. */
export const GROUP_LABEL =
  'select-none px-1.5 py-1 text-[length:var(--font-size-1)] leading-[var(--line-height-1)] text-text-3';

/**
 * §5.3 — 1px `border-base`, as wide as the rows: it sits inside the panel's
 * 6px padding and never touches the panel edge. It carries no margin of its
 * own — the 4px above and below come from the column's gap (MENU_STACK).
 */
export const SEPARATOR = 'h-px bg-border-base';

/**
 * §6.5 — the one line an empty / no-match / loading panel shows. No
 * illustration: a temporary overlay is not a card.
 */
export const PANEL_MESSAGE =
  'flex items-center justify-center gap-2 py-4 text-[length:var(--font-size-3)] leading-[var(--line-height-3)] text-text-3';
