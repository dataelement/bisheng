import * as React from 'react';
import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Tooltip } from '../Tooltip/Tooltip';

/**
 * Breadcrumb — where the current page sits in the structure (组件-Breadcrumb面包屑.md v1).
 *
 * The page hands over the FULL chain, root first and current page last; every
 * rule the spec pins down lives here and a business page never restates it:
 * the 96px cap on parent names with its truncation tooltip (§4), the collapse
 * into an ellipsis menu past four levels (§5), the narrow-screen thresholds
 * (§6), and the `nav` / `aria-current` wiring (§7). A single-level chain
 * renders nothing at all (§1) — an empty breadcrumb row costs a line of page
 * and gives back no information.
 *
 * Not this component: "step 3 of 5" (that is a step bar, which only looks
 * alike), and browsing history — the chain is structural, not where you came
 * from.
 */
export interface BreadcrumbItem {
  /** React key + menu identity. Falls back to the index when omitted. */
  key?: string;
  /** Displayed name. Truncation is the component's job, not the caller's. */
  title: string;
  /** Called when the level is activated. Every level must open a real page (§2). */
  onClick?: () => void;
  /** Renders the level as a real link (middle-click, "open in new tab"). */
  href?: string;
}

export interface BreadcrumbProps {
  /** Full chain, root first, current page last. Fewer than 2 renders nothing. */
  items: BreadcrumbItem[];
  /** Collapse once the chain is LONGER than this (§5.1). */
  maxItems?: number;
  /** How many trailing levels stay visible, current page included (§5.1). */
  itemsAfterCollapse?: number;
  /**
   * Tooltip + `aria-label` for the ellipsis trigger, given the number of levels
   * it hides — "点击展开省略的 N 层" (§5.2). A function because the count is the
   * component's to know and the wording is the caller's: this library holds no
   * i18n keys.
   */
  expandLabel: (hiddenCount: number) => string;
  /** `aria-label` of the wrapping `nav` (§7). */
  ariaLabel?: string;
  className?: string;
}

/** §4 — 96px ≈ 8 CJK characters at 12px. Capped by width, never by counting characters. */
const PARENT_MAX_WIDTH = 'max-w-[96px]';

/** §5.1 — desktop: collapse past 4 levels, keep the last 2 (current page included). */
const DEFAULT_MAX_ITEMS = 4;
const DEFAULT_ITEMS_AFTER_COLLAPSE = 2;

/** §6 — narrow: collapse past 3 levels, leaving `root · … · current`. */
const NARROW_MAX_ITEMS = 3;
const NARROW_ITEMS_AFTER_COLLAPSE = 1;

/** §6 — the shared 576px breakpoint (基础-多端适配原则.md), not one of our own. */
const NARROW_QUERY = '(max-width: 575.98px)';

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = React.useState(false);

  React.useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const list = window.matchMedia(query);
    const sync = () => setMatches(list.matches);
    sync();
    list.addEventListener('change', sync);
    return () => list.removeEventListener('change', sync);
  }, [query]);

  return matches;
}

/** §3 — an icon, never a text `>`: `>` is a maths glyph that sits low next to CJK. */
function Separator() {
  return <Outlined.Right className="size-4 shrink-0 text-text-4" aria-hidden />;
}

/** True once the element's own content is wider than the box drawn for it. */
function isClipped(el: HTMLElement | null): boolean {
  return el ? el.scrollWidth > el.clientWidth : false;
}

interface CrumbProps {
  item: BreadcrumbItem;
  className?: string;
}

/**
 * A clickable level. §3/§4: hint grey, brand on hover, capped at 96px, and the
 * full-name tooltip appears ONLY when the name really is clipped — measured on
 * pointer-enter, so a chain of short names mounts no tooltips at all.
 */
function Crumb({ item, className }: CrumbProps) {
  const [clipped, setClipped] = React.useState(false);
  const handleEnter = (event: React.PointerEvent<HTMLElement>) => {
    setClipped(isClipped(event.currentTarget));
  };

  const shared = {
    onPointerEnter: handleEnter,
    className: cn(
      'block shrink-0 truncate text-text-3 outline-none transition-colors',
      'hover:text-blue-600 focus-visible:ring-2 focus-visible:ring-blue-600/40',
      PARENT_MAX_WIDTH,
      className,
    ),
  };

  const crumb = item.href ? (
    <a href={item.href} onClick={item.onClick} {...shared}>
      {item.title}
    </a>
  ) : (
    <button type="button" onClick={item.onClick} {...shared}>
      {item.title}
    </button>
  );

  return (
    <Tooltip content={item.title} side="bottom" disabled={!clipped}>
      {crumb}
    </Tooltip>
  );
}

/**
 * A row of the collapsed-levels menu. §5.3: the full name, capped only by the
 * menu's own 240px — the user opened the menu to READ the name, so eliding it
 * a second time would lose the information twice. The tooltip goes to the right
 * of the panel so it never covers the rows below.
 */
function MenuItemName({ title }: { title: string }) {
  const [clipped, setClipped] = React.useState(false);

  return (
    <Tooltip content={title} side="right" disabled={!clipped}>
      <span
        className="min-w-0 flex-1 truncate"
        onPointerEnter={(event) => setClipped(isClipped(event.currentTarget))}
      >
        {title}
      </span>
    </Tooltip>
  );
}

export function Breadcrumb({
  items,
  maxItems = DEFAULT_MAX_ITEMS,
  itemsAfterCollapse = DEFAULT_ITEMS_AFTER_COLLAPSE,
  expandLabel,
  ariaLabel = 'breadcrumb',
  className,
}: BreadcrumbProps) {
  const narrow = useMediaQuery(NARROW_QUERY);
  const [menuOpen, setMenuOpen] = React.useState(false);
  // The ellipsis tooltip is driven entirely by pointer enter/leave: Radix would
  // otherwise re-open it from the focus it hands back to the trigger when the
  // menu closes, and leave it standing there.
  const [tipOpen, setTipOpen] = React.useState(false);
  const [currentClipped, setCurrentClipped] = React.useState(false);

  // §6 — a narrow viewport only ever tightens what the caller asked for.
  const effectiveMax = narrow ? Math.min(maxItems, NARROW_MAX_ITEMS) : maxItems;
  const effectiveAfter = narrow
    ? Math.min(itemsAfterCollapse, NARROW_ITEMS_AFTER_COLLAPSE)
    : itemsAfterCollapse;

  // §1 — one level is the page title again, not a path.
  if (items.length < 2) {
    return null;
  }

  const current = items[items.length - 1];
  // §5.1 — the root and the last `itemsAfterCollapse` levels always stay out;
  // whatever sits between them goes behind the ellipsis, which is therefore
  // always the second position.
  const hidden = items.length > effectiveMax
    ? items.slice(1, Math.max(1, items.length - effectiveAfter))
    : [];
  const collapsed = hidden.length > 0;
  const head = collapsed ? items.slice(0, 1) : items.slice(0, -1);
  const tail = collapsed ? items.slice(1 + hidden.length, -1) : [];
  const keyOf = (item: BreadcrumbItem, index: number) => item.key ?? String(index);

  return (
    <nav
      aria-label={ariaLabel}
      // §3 — 12/24, 2px either side of each separator; §4 — never wraps.
      className={cn(
        'flex min-w-0 flex-nowrap items-center gap-0.5 text-caption leading-6',
        className,
      )}
    >
      {head.map((item, index) => (
        <span key={keyOf(item, index)} className="flex shrink-0 items-center gap-0.5">
          <Crumb item={item} />
          <Separator />
        </span>
      ))}

      {collapsed && (
        <span className="flex shrink-0 items-center gap-0.5">
          <DropdownMenuPrimitive.Root
            open={menuOpen}
            onOpenChange={(open) => {
              setMenuOpen(open);
              if (open) {
                setTipOpen(false);
              }
            }}
          >
            {/* §5.2 — a bare `…` at rest (a permanent chip weighs the row down);
                the 24×24 container appears on hover and stays while the menu is
                open. Pointer + tooltip + that container are the three signals
                that it can be clicked, and none of them is optional. */}
            <Tooltip
              content={expandLabel(hidden.length)}
              side="bottom"
              open={tipOpen}
              disabled={!tipOpen || menuOpen}
            >
              <DropdownMenuPrimitive.Trigger
                aria-label={expandLabel(hidden.length)}
                onPointerEnter={() => setTipOpen(!menuOpen)}
                onPointerLeave={() => setTipOpen(false)}
                className={cn(
                  'btn-touch-hit relative flex size-6 shrink-0 cursor-pointer items-center',
                  'justify-center rounded leading-none text-text-3 outline-none transition-colors',
                  'hover:bg-fill-2 data-[state=open]:bg-fill-2',
                  'focus-visible:ring-2 focus-visible:ring-blue-600/40',
                )}
              >
                …
              </DropdownMenuPrimitive.Trigger>
            </Tooltip>
            <DropdownMenuPrimitive.Portal>
              {/* §5.3 — one column, one level per row, top = highest ancestor.
                  No separators and no indent: the vertical order already says
                  it, and indenting a ninth level would eat the width. Radix
                  brings Esc / outside-click / arrow keys / aria-expanded. */}
              <DropdownMenuPrimitive.Content
                align="center"
                sideOffset={4}
                className={cn(
                  'z-popover max-h-80 min-w-[120px] max-w-[240px] overflow-y-auto',
                  'rounded-lg bg-bg-page p-1 shadow-popup',
                )}
              >
                {hidden.map((item, index) => (
                  <DropdownMenuPrimitive.Item
                    key={keyOf(item, index + 1)}
                    onSelect={item.onClick}
                    // The whole row is the target, and it wears the same colors
                    // as the crumbs outside: hint grey, brand on hover.
                    className={cn(
                      'flex h-8 cursor-pointer select-none items-center rounded px-3',
                      'text-caption text-text-3 outline-none transition-colors',
                      'data-[highlighted]:bg-fill-1 data-[highlighted]:text-blue-600',
                    )}
                  >
                    <MenuItemName title={item.title} />
                  </DropdownMenuPrimitive.Item>
                ))}
              </DropdownMenuPrimitive.Content>
            </DropdownMenuPrimitive.Portal>
          </DropdownMenuPrimitive.Root>
          <Separator />
        </span>
      )}

      {tail.map((item, index) => (
        <span
          key={keyOf(item, 1 + hidden.length + index)}
          className="flex shrink-0 items-center gap-0.5"
        >
          <Crumb item={item} />
          <Separator />
        </span>
      ))}

      {/* §2/§3 — the current page: one shade darker ("you are here"), not a
          link and not hoverable, and free of the 96px cap — only the page
          width limits it, which is why it still gets the clipping tooltip. */}
      <Tooltip content={current.title} side="bottom" disabled={!currentClipped}>
        <span
          aria-current="page"
          className="min-w-0 truncate text-text-1"
          onPointerEnter={(event) => setCurrentClipped(isClipped(event.currentTarget))}
        >
          {current.title}
        </span>
      </Tooltip>
    </nav>
  );
}
