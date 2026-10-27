import * as React from 'react';
import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import {
  DEFAULT_PANEL_RADIUS,
  GROUP_LABEL,
  MENU_STACK,
  OPTION_CHECK,
  OPTION_ICON,
  PANEL_COLLISION_PADDING,
  PANEL_SIDE_OFFSET,
  SEPARATOR,
  optionClass,
  panelClass,
  type PanelRadius,
} from '../shared/menuSurface';
import { Tooltip } from '../Tooltip/Tooltip';

/**
 * Dropdown — a set of related ACTIONS folded behind one button
 * (组件-Dropdown下拉菜单.md v1). Picking one runs it; the trigger never changes.
 *
 * The panel shell, the 32px row, group titles and separators are Select's
 * (§4 → Select §5, shared through `shared/menuSurface.ts`). What this file
 * adds and a page cannot restate: content-sized width 120–280px (§4), danger
 * rows in red with a red-tinted hover (§5), disabled rows grayed out rather
 * than hidden (§6), the right-side check of a toggle row (§6), click by
 * default with an optional 100ms hover mode (§7), one level of submenu (§7.1),
 * and a trigger that keeps its hover look while the menu is open (§3).
 *
 * Not this component: anything whose pick should show up in the box afterwards
 * — that is Select (§1). Fewer than 3 actions should simply be buttons.
 * Danger rows do NOT confirm by themselves: call `useConfirm` from `onSelect`;
 * the menu has already closed by then, so the two overlays never stack (§5).
 */

/** §7 — hover mode: 100ms to open, 100ms grace before closing (Tooltip's timing). */
const HOVER_OPEN_DELAY = 100;
const HOVER_CLOSE_DELAY = 100;

/** §4 — content width, never the trigger's (a "⋯" is 24px wide). */
const MENU_WIDTH = 'min-w-[120px] max-w-[280px]';

/**
 * 落地 §4 — Radix measures the submenu from the parent ROW, which sits inside
 * the panel's 6px padding. Add it back so the gap is 4px from the panel EDGE
 * (§7.1), and cancel it vertically so the first sub item lines up with its
 * parent row.
 */
const PANEL_PADDING = 6;
const SUB_SIDE_OFFSET = PANEL_SIDE_OFFSET + PANEL_PADDING;
const SUB_ALIGN_OFFSET = -PANEL_PADDING;

const RadiusContext = React.createContext<PanelRadius>(DEFAULT_PANEL_RADIUS);

function canHover(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(hover: hover)').matches === true;
}

export interface DropdownProps {
  /** The trigger: a Button (with `DropdownChevron` after its text), a "⋯" icon button, … */
  children: React.ReactElement;
  /** The menu body: `DropdownItem` / `DropdownGroup` / `DropdownSeparator` / `DropdownSub`. */
  menu: React.ReactNode;
  /**
   * §7 — `click` (default) everywhere; `hover` only for nav / toolbar menus
   * people scan. Touch has no hover, so it falls back to click there.
   */
  trigger?: 'click' | 'hover';
  /** §7 — `end` when the trigger sits at the right edge (a card's top-right "⋯"). */
  align?: 'start' | 'end';
  side?: 'top' | 'bottom';
  /** §4 — panel radius rung, default `xl`; rows follow automatically. */
  panelRadius?: PanelRadius;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Override focus restoration when an action moves focus into another control. */
  onCloseAutoFocus?: React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>['onCloseAutoFocus'];
  disabled?: boolean;
  /** Layout only — radius goes through `panelRadius`. */
  panelClassName?: string;
}

export function Dropdown({
  children,
  menu,
  trigger = 'click',
  align = 'start',
  side = 'bottom',
  panelRadius = DEFAULT_PANEL_RADIUS,
  open: openProp,
  defaultOpen = false,
  onOpenChange,
  onCloseAutoFocus,
  disabled = false,
  panelClassName,
}: DropdownProps) {
  const [innerOpen, setInnerOpen] = React.useState(defaultOpen);
  const isOpen = openProp ?? innerOpen;
  const setOpen = React.useCallback(
    (next: boolean) => {
      if (openProp === undefined) setInnerOpen(next);
      onOpenChange?.(next);
    },
    [openProp, onOpenChange],
  );

  // §7 hover mode: open after 100ms on the trigger, stay open while the
  // pointer is on the trigger OR the panel, close 100ms after it left both.
  const hover = trigger === 'hover';
  const timer = React.useRef<number>();
  React.useEffect(() => () => window.clearTimeout(timer.current), []);
  const schedule = (next: boolean) => {
    if (!hover || disabled || !canHover()) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(
      () => setOpen(next),
      next ? HOVER_OPEN_DELAY : HOVER_CLOSE_DELAY,
    );
  };
  const hoverHandlers = hover
    ? { onPointerEnter: () => schedule(true), onPointerLeave: () => schedule(false) }
    : {};

  return (
    <RadiusContext.Provider value={panelRadius}>
      {/* A hover menu must not trap the page: no modal layer, no scroll lock. */}
      <DropdownMenuPrimitive.Root open={isOpen} onOpenChange={setOpen} modal={!hover}>
        <DropdownMenuPrimitive.Trigger
          asChild
          disabled={disabled}
          // §3 — the trigger keeps its hover look while open (Button reads
          // this attribute); `group/dropdown` lets DropdownChevron turn over.
          data-menu-open={isOpen ? '' : undefined}
          className="group/dropdown"
          {...hoverHandlers}
        >
          {children}
        </DropdownMenuPrimitive.Trigger>
        <DropdownMenuPrimitive.Portal>
          <DropdownMenuPrimitive.Content
            onCloseAutoFocus={onCloseAutoFocus}
            side={side}
            align={align}
            sideOffset={PANEL_SIDE_OFFSET}
            collisionPadding={PANEL_COLLISION_PADDING}
            className={panelClass(panelRadius, cn(MENU_WIDTH, panelClassName))}
            {...hoverHandlers}
          >
            {menu}
          </DropdownMenuPrimitive.Content>
        </DropdownMenuPrimitive.Portal>
      </DropdownMenuPrimitive.Root>
    </RadiusContext.Provider>
  );
}

export interface DropdownChevronProps {
  className?: string;
}

/**
 * §3 — the down arrow after a trigger's text. Turns over while its menu is
 * open; sized by the Button's own icon ladder.
 */
export function DropdownChevron({ className }: DropdownChevronProps) {
  return (
    <Outlined.Down
      aria-hidden
      className={cn('transition-transform group-data-[menu-open]/dropdown:rotate-180', className)}
    />
  );
}

export interface DropdownItemProps {
  /** §4.1 — a verb first; end with "…" when the action asks for more input. */
  children: React.ReactNode;
  /** §4 — 16px; either every item in a group has one or none do. */
  icon?: React.ReactNode;
  /** §4 — keyboard shortcut text, right-aligned in hint gray. */
  shortcut?: React.ReactNode;
  /** §5 — irreversible actions: red, last group, confirmed from `onSelect`. */
  danger?: boolean;
  /** §6 — grayed out, never hidden. Say why with `disabledReason`. */
  disabled?: boolean;
  /** §6 — shown on hover of a disabled item ("无编辑权限"). */
  disabledReason?: string;
  /**
   * §6 — a setting toggled from the menu: a check on the right while on.
   * Leave undefined for an ordinary action.
   */
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  /** Runs on selection; use onCloseAutoFocus on Dropdown to hand focus off after dismissal. */
  onSelect?: () => void;
  className?: string;
}

/** §5 — red text and icon; hover goes to a red tint, never to gray. */
const DANGER_ITEM = 'text-danger data-[highlighted]:bg-danger/10';

/** §4 — shortcut: 12/20 hint gray, at least 24px from the label. */
const SHORTCUT =
  'ml-auto shrink-0 pl-6 text-[length:var(--font-size-1)] leading-[var(--line-height-1)] text-text-3';

function ItemBody({
  icon,
  children,
  shortcut,
  checked,
}: Pick<DropdownItemProps, 'icon' | 'children' | 'shortcut' | 'checked'>) {
  return (
    <>
      {icon !== undefined && <span className={OPTION_ICON}>{icon}</span>}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {shortcut !== undefined && <span className={SHORTCUT}>{shortcut}</span>}
      {checked && <Outlined.Check aria-hidden className={OPTION_CHECK} />}
    </>
  );
}

export const DropdownItem = React.forwardRef<HTMLDivElement, DropdownItemProps>(
  function DropdownItem(
    {
      children,
      icon,
      shortcut,
      danger = false,
      disabled = false,
      disabledReason,
      checked,
      onCheckedChange,
      onSelect,
      className,
    },
    ref,
  ) {
    const radius = React.useContext(RadiusContext);
    const itemClass = optionClass(radius, cn(danger && !disabled && DANGER_ITEM, className));
    const body = (
      <ItemBody icon={icon} shortcut={shortcut} checked={checked}>
        {children}
      </ItemBody>
    );

    const item =
      checked === undefined ? (
        <DropdownMenuPrimitive.Item
          ref={ref}
          disabled={disabled}
          onSelect={onSelect}
          className={itemClass}
        >
          {body}
        </DropdownMenuPrimitive.Item>
      ) : (
        <DropdownMenuPrimitive.CheckboxItem
          ref={ref}
          disabled={disabled}
          checked={checked}
          onCheckedChange={onCheckedChange}
          onSelect={onSelect}
          className={itemClass}
        >
          {body}
        </DropdownMenuPrimitive.CheckboxItem>
      );

    if (!disabled || !disabledReason) return item;
    // Radix keeps pointer events on a disabled item, so a plain wrapper is
    // enough to carry the hover — Tooltip's own disabled-trigger hot zone
    // would put a focusable span inside the menu.
    return (
      <Tooltip content={disabledReason} side="right">
        <div>{item}</div>
      </Tooltip>
    );
  },
);

export interface DropdownGroupProps {
  /** §5.3 — optional title; groups are otherwise split by `DropdownSeparator`. */
  label?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * §4 — at most 3 groups per menu. The group wrapper repeats the column's 4px
 * rhythm: the panel's own children are the groups, so rows inside one would
 * otherwise sit adjacent while only rows across groups got the gap.
 */
export function DropdownGroup({ label, children }: DropdownGroupProps) {
  return (
    <DropdownMenuPrimitive.Group className={MENU_STACK}>
      {label !== undefined && (
        <DropdownMenuPrimitive.Label className={GROUP_LABEL}>{label}</DropdownMenuPrimitive.Label>
      )}
      {children}
    </DropdownMenuPrimitive.Group>
  );
}

export function DropdownSeparator() {
  return <DropdownMenuPrimitive.Separator className={SEPARATOR} />;
}

export interface DropdownSubProps {
  /** §7.1 — say what is inside: "移动到…", "导出为". */
  label: React.ReactNode;
  icon?: React.ReactNode;
  disabled?: boolean;
  /** `DropdownItem`s only — §7.1 allows ONE level, so no nested `DropdownSub`. */
  children: React.ReactNode;
}

/** §7.1 — one level of submenu, ~5 items, opening to the right (flipping when it must). */
export function DropdownSub({ label, icon, disabled = false, children }: DropdownSubProps) {
  const radius = React.useContext(RadiusContext);
  return (
    <DropdownMenuPrimitive.Sub>
      <DropdownMenuPrimitive.SubTrigger
        disabled={disabled}
        // The parent row stays highlighted while its submenu is open.
        className={optionClass(radius, 'data-[state=open]:bg-fill-2')}
      >
        <ItemBody icon={icon}>{label}</ItemBody>
        <Outlined.Right aria-hidden className="size-4 shrink-0 text-text-3" />
      </DropdownMenuPrimitive.SubTrigger>
      <DropdownMenuPrimitive.Portal>
        <DropdownMenuPrimitive.SubContent
          sideOffset={SUB_SIDE_OFFSET}
          alignOffset={SUB_ALIGN_OFFSET}
          collisionPadding={PANEL_COLLISION_PADDING}
          className={panelClass(radius, MENU_WIDTH)}
        >
          {children}
        </DropdownMenuPrimitive.SubContent>
      </DropdownMenuPrimitive.Portal>
    </DropdownMenuPrimitive.Sub>
  );
}
