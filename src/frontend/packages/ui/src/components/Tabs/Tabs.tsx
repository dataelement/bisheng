import * as React from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import cn from '../../utils/cn';

/**
 * Tabs — design-system base component (组件-Tabs标签页.md v1).
 *
 * Groups PEER content blocks into one area — switching changes WHERE you are,
 * so it is navigation. The same content shown a different way is a Segmented
 * (判别表 in 组件-Segmented分段控制器.md §1). Line type ONLY — no card tabs, no
 * closable tabs (§2). Baked in per spec: left-aligned tab row over a full-width
 * 1px divider, 24px between tabs, first tab flush with the content edge (§2);
 * three sizes on the 24/32/40 ladder; unselected weight 400, selected 500 —
 * every tab reserves its width at 500 via an invisible bold copy of the label
 * (antd's trick), so bolding never moves the neighbors or the indicator (§3);
 * selected text + a 2px indicator sliding 200ms under the selected tab, in
 * the brand color by default or in ink via `variant="neutral"` (§5); content
 * swaps instantly, no transition (§5);
 * overflow scrolls horizontally with fading edges, never wraps, the selected
 * tab keeps itself visible (§4); ≥44px touch hot zones (§6). Accessibility is
 * the WAI-ARIA tabs pattern in automatic mode: arrow keys move focus AND
 * activate, Home/End jump to the ends (§落地 2).
 */

export type TabsSize = 'small' | 'medium' | 'large';

/** §5 — how the selected tab speaks: brand color (default) or ink (text-1). */
export type TabsVariant = 'brand' | 'neutral';

export interface TabItem {
  /** Identity of the tab; also what `activeKey` / `onChange` speak. */
  key: string;
  /** 2–6 chars, same length across the set reads best (§4); never truncated. */
  label: React.ReactNode;
  /** Optional leading icon — all tabs in a set have one or none do (§4). */
  icon?: React.ReactNode;
  /** §5 — grays out and skips focus; prefer not rendering a dead tab at all. */
  disabled?: boolean;
  /** Panel content. Omit on every item to use Tabs as a bare bar (routing). */
  children?: React.ReactNode;
}

/** §3 — row height 24/32/40; font follows the type scale per rung (14/14/16).
 * Font sizes reference the PRIMITIVE scale vars — control text must not follow
 * the ≤768px body remap (same rationale as Button §3). */
const ROW_SIZE: Record<TabsSize, string> = {
  small: 'h-6 text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  medium: 'h-8 text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  large: 'h-10 text-[length:var(--font-size-4)] leading-[var(--line-height-4)]',
};

/** §4 — icon rides the 14/16/18 ladder, 8px gap to the text (4px on small). */
const TAB_SIZE: Record<TabsSize, string> = {
  small: 'gap-1 [&_svg]:size-3.5',
  medium: 'gap-2 [&_svg]:size-4',
  large: 'gap-2 [&_svg]:size-[18px]',
};

/** §5 — selected-state color per variant. `brand` follows the blue⇄green
 * theme (and the dark brand ramp — see the use site). `neutral`
 * speaks in ink: selected text and indicator are text-1, which already flips
 * to near-white in dark mode — no dark override needed, and no contrast debt
 * (text-1 is the loudest text on either background). Selection then rests on
 * weight 500 + the indicator alone, so neutral is for surfaces where a brand
 * accent would fight nearby brand elements (§5). */
const VARIANT: Record<TabsVariant, { tab: string; indicator: string }> = {
  brand: {
    // Dark needs no override: blue-500 resolves through the dark brand ramp
    // (tokens.css .dark → #3C7EFF blue / #3CB062 green), bright AND saturated
    // on #121212 — the fix §5's 实测 ladder (500 too dim / 300 washed out /
    // interim 400) was waiting for.
    tab: 'data-[state=active]:text-blue-500 data-[state=active]:hover:text-blue-500',
    indicator: 'bg-blue-500',
  },
  neutral: {
    tab: 'data-[state=active]:text-text-1 data-[state=active]:hover:text-text-1',
    indicator: 'bg-text-1',
  },
};

/** §4 — fading edges while overflowing: mask off the side(s) that continue. */
const EDGE_FADE = {
  none: undefined,
  left: 'linear-gradient(to right, transparent, black 24px)',
  right: 'linear-gradient(to left, transparent, black 24px)',
  both: 'linear-gradient(to right, transparent, black 24px, black calc(100% - 24px), transparent)',
};

export interface TabsProps {
  /** At least 2 — a single tab is just content, not tabs (§1). */
  items: TabItem[];
  /** §3 — deeper containers take smaller rungs: page header large, dialogs small. */
  size?: TabsSize;
  /**
   * §5 — `brand` (default): selected tab in the brand color. `neutral`:
   * selected tab in ink (text-1) — for surfaces where a brand accent would
   * compete with nearby brand elements; selection rests on weight + indicator.
   */
  variant?: TabsVariant;
  /** Controlled selected key; use `defaultActiveKey` for uncontrolled. */
  activeKey?: string;
  defaultActiveKey?: string;
  onChange?: (key: string) => void;
  /**
   * §2 — light operations at the right end of the tab row (refresh, a filter),
   * vertically centered; heavy actions belong in the content area.
   */
  extra?: React.ReactNode;
  className?: string;
}

function Tabs({
  items,
  size = 'medium',
  variant = 'brand',
  activeKey,
  defaultActiveKey,
  onChange,
  extra,
  className,
}: TabsProps) {
  const listRef = React.useRef<HTMLDivElement>(null);
  const tabRefs = React.useRef(new Map<string, HTMLButtonElement>());

  // The current key is mirrored locally so the indicator knows where to sit in
  // both controlled and uncontrolled mode.
  const [innerKey, setInnerKey] = React.useState(defaultActiveKey ?? items.find((i) => !i.disabled)?.key);
  const current = activeKey !== undefined ? activeKey : innerKey;

  // §5 — the indicator is ONE absolute element that slides (200ms) to the
  // selected tab; per-tab border-bottoms cannot slide. Measured relative to
  // the list, so it scrolls together with the tabs.
  const [indicator, setIndicator] = React.useState<{ left: number; width: number } | null>(null);
  // §4 — which edges continue out of view and therefore fade.
  const [fade, setFade] = React.useState<keyof typeof EDGE_FADE>('none');

  const updateFade = React.useCallback(() => {
    const list = listRef.current;
    if (!list) return;
    const left = list.scrollLeft > 1;
    const right = list.scrollLeft + list.clientWidth < list.scrollWidth - 1;
    setFade(left ? (right ? 'both' : 'left') : right ? 'right' : 'none');
  }, []);

  React.useLayoutEffect(() => {
    const list = listRef.current;
    const tab = current !== undefined ? tabRefs.current.get(current) : undefined;
    const measure = () => {
      setIndicator(tab ? { left: tab.offsetLeft, width: tab.offsetWidth } : null);
      updateFade();
    };
    measure();
    // Re-measure on any size change of the list or the selected tab (container
    // resize, font swap-in, label change).
    const ro = new ResizeObserver(measure);
    if (list) ro.observe(list);
    if (tab) ro.observe(tab);
    return () => ro.disconnect();
  }, [current, items, size, updateFade]);

  // §4 — the selected tab keeps itself inside the visible range.
  React.useEffect(() => {
    const list = listRef.current;
    const tab = current !== undefined ? tabRefs.current.get(current) : undefined;
    if (list && tab && list.scrollWidth > list.clientWidth) {
      tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  }, [current]);

  const handleChange = (next: string) => {
    setInnerKey(next);
    onChange?.(next);
  };

  return (
    <TabsPrimitive.Root value={current} onValueChange={handleChange} activationMode="automatic" className={className}>
      {/* §2 — one 1px divider under the WHOLE row, extra area included. */}
      <div className="flex items-end border-b border-border-base">
        <TabsPrimitive.List
          ref={listRef}
          onScroll={updateFade}
          className={cn(
            // §4 — overflow scrolls, never wraps; the scrollbar itself is
            // hidden (the fading edges are the affordance).
            // -mb-px sinks the list 1px onto the wrapper's border-b so the
            // bottom-0 indicator paints OVER the gray divider instead of
            // stacking above it (the indicator can't use -bottom-px itself:
            // overflow-x-auto forces overflow-y to auto, which would clip it).
            'relative -mb-px flex min-w-0 flex-1 items-center gap-6 overflow-x-auto',
            '[-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
            ROW_SIZE[size],
          )}
          style={{ maskImage: EDGE_FADE[fade], WebkitMaskImage: EDGE_FADE[fade] }}
        >
          {items.map((item) => (
            <TabsPrimitive.Trigger
              key={item.key}
              value={item.key}
              disabled={item.disabled}
              ref={(el) => {
                if (el) tabRefs.current.set(item.key, el);
                else tabRefs.current.delete(item.key);
              }}
              className={cn(
                // relative anchors the ≥44px touch hot zone (§6); rounded only
                // softens the keyboard focus ring (§5 — 2px gray, input's ring).
                'btn-touch-hit relative inline-flex h-full shrink-0 cursor-pointer items-center whitespace-nowrap rounded font-normal outline-none transition-colors focus-visible:shadow-focus',
                // §5 — unselected text-2, hover deepens to text-1, selected
                // speaks per variant (brand color or ink — see VARIANT), one
                // weight step up (the label box already reserves this width).
                'text-text-2 hover:text-text-1 data-[state=active]:font-medium',
                VARIANT[variant].tab,
                'disabled:cursor-not-allowed disabled:text-btn-disabled-text',
                TAB_SIZE[size],
              )}
            >
              {item.icon}
              {/* §3 — the box is sized by an invisible 500-weight copy, so the
                  400⇄500 flip never widens the tab (pure-CJK labels would not
                  move anyway — CJK advances are weight-independent — but Latin
                  and digits do). The visible copy centers in the reserved box. */}
              <span className="relative whitespace-nowrap">
                <span aria-hidden className="invisible font-medium">
                  {item.label}
                </span>
                <span className="absolute inset-0 flex items-center justify-center">{item.label}</span>
              </span>
            </TabsPrimitive.Trigger>
          ))}
          {/* §5 — 2px brand indicator on the divider, text-wide, 200ms slide. */}
          {indicator && (
            <span
              aria-hidden
              className={cn(
                'absolute bottom-0 left-0 h-0.5 transition-[transform,width] duration-200',
                VARIANT[variant].indicator,
              )}
              style={{ width: indicator.width, transform: `translateX(${indicator.left}px)` }}
            />
          )}
        </TabsPrimitive.List>
        {extra !== undefined && <div className="flex shrink-0 items-center self-center pl-6">{extra}</div>}
      </div>
      {/* §5 — the panel swaps instantly; no transition on content. */}
      {items
        .filter((item) => item.children !== undefined)
        .map((item) => (
          <TabsPrimitive.Content key={item.key} value={item.key} className="outline-none">
            {item.children}
          </TabsPrimitive.Content>
        ))}
    </TabsPrimitive.Root>
  );
}

export { Tabs };
