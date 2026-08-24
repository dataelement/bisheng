import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import cn from '../../utils/cn';

/**
 * Tooltip — one line of plain text explaining a control (组件-Tooltip文字提示.md v1).
 *
 * What the component pins down and a page cannot restate: the translucent dark
 * surface (§3), the 100ms hover delay with its 300ms skip window (§6), the
 * top-centre default with auto-flip (§5), the focusable hot zone a disabled
 * trigger needs to be hoverable at all (§7), and the top overlay tier so a
 * tooltip can appear over a dialog (落地 §6).
 *
 * Not this component: anything with a link, a button or a field inside — that
 * is a Popover, because keyboard focus never enters a tooltip and those
 * controls would not exist for keyboard users (§2). There is deliberately no
 * "rich tooltip" with a title and actions.
 *
 * Touch: nothing shows, by design (§8). Radix does not respond to touch and we
 * keep it that way — a long-press substitute collides with text selection and
 * the system menu. Which is the whole constraint on what may go in a tooltip:
 * only what costs the user nothing to miss.
 */

/** §6 — 100ms to appear; another tooltip within 300ms skips the wait entirely. */
const DELAY_DURATION = 100;
const SKIP_DELAY_DURATION = 300;

/**
 * §3 — every tooltip carries an arrow; there is no arrow-less variant, so a
 * bubble always reads as belonging to one specific control. It is an 8px
 * square rotated 45°, so what shows is a triangle 8√2 ≈ 11px wide and half
 * that tall. Radix draws it as an SVG placed against the bubble instead of a
 * rotated box overlapping it, so the two never stack their alpha into a
 * darker seam.
 */
const ARROW_WIDTH = 11;
const ARROW_HEIGHT = 6;

/** §3 — 4px between trigger and bubble, measured from the arrow tip. */
const TRIGGER_GAP = 4;

/**
 * §3 — deepest grey at 90%, and the lightest grey for the text rather than a
 * literal `#fff`: both ends of the ramp flip under `.dark`, so the pair stays
 * legible there instead of leaving white text on a near-white panel. No
 * backdrop blur (root AGENTS.md), no bare hex.
 */
const SURFACE = 'rgb(var(--arco-gray-10) / 0.9)';
const BUBBLE_STYLE: React.CSSProperties = { background: SURFACE, color: 'rgb(var(--arco-gray-1))' };
const ARROW_STYLE: React.CSSProperties = { fill: SURFACE };

/**
 * §3 — 14/22 body type, 6/12 padding (34px tall on one line, near enough to a
 * 32px control), 6px radius, wraps past 250px, popup shadow, no border: on a
 * dark surface a 1px edge has nothing to do. `z-tooltip` is the top of the four
 * overlay tiers (落地 §6) — a tooltip must be able to sit over a dialog.
 * Text stays selectable: §6 lets the pointer move into the bubble to copy it.
 */
const BUBBLE_CLASS =
  'z-tooltip max-w-[250px] break-words rounded-md px-3 py-1.5 text-body shadow-popup ' +
  'data-[state=delayed-open]:animate-tooltip-in data-[state=instant-open]:animate-tooltip-in ' +
  'data-[state=closed]:animate-tooltip-out motion-reduce:animate-none';

/**
 * True when a `TooltipProvider` is above us. Radix's own provider context is
 * private, and a provider nested inside every tooltip would shadow the app-root
 * one — killing the skip window (§6) that only a SHARED provider can give.
 */
const HasProviderContext = React.createContext(false);

export interface TooltipProviderProps {
  children: React.ReactNode;
  /** §6 — override only with a reason; the defaults ARE the spec. */
  delayDuration?: number;
  skipDelayDuration?: number;
}

/**
 * Optional, and worth mounting once at the app root: it is what makes the next
 * tooltip in a row of icon buttons appear instantly (§6) and what keeps only
 * one tooltip open at a time. Without it every `<Tooltip>` falls back to a
 * provider of its own, which is correct but has no shared skip window.
 */
export function TooltipProvider({
  children,
  delayDuration = DELAY_DURATION,
  skipDelayDuration = SKIP_DELAY_DURATION,
}: TooltipProviderProps) {
  return (
    <HasProviderContext.Provider value={true}>
      <TooltipPrimitive.Provider
        delayDuration={delayDuration}
        skipDelayDuration={skipDelayDuration}
      >
        {children}
      </TooltipPrimitive.Provider>
    </HasProviderContext.Provider>
  );
}

export interface TooltipProps {
  /** One line of plain text (§4). Nothing interactive — that would be a Popover. */
  content: React.ReactNode;
  /**
   * The trigger. §7: it should be something focusable (button, link, field) —
   * on a bare `span` a keyboard user can never reach the tooltip. A disabled
   * control is handled here, not by the page.
   */
  children: React.ReactElement;
  /** §5 — 12 positions; top-centre by default, auto-flipped when space runs out. */
  side?: 'top' | 'right' | 'bottom' | 'left';
  align?: 'start' | 'center' | 'end';
  /**
   * Keep the trigger, drop the tooltip. For "only when the text is actually
   * clipped" cases: nothing is mounted, so no stray portal and no bubble that
   * re-opens from the focus Radix hands back after a menu closes.
   */
  disabled?: boolean;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Extra classes on the bubble. The surface itself is not a per-page decision. */
  contentClassName?: string;
}

/**
 * §7 — a disabled control dispatches no pointer events, so its "why is this
 * off?" tooltip would never fire. Wrap it in a focusable hot zone that takes
 * the hover instead. Internal on purpose: the spec forbids pages hand-rolling
 * this each time.
 */
function useTriggerElement(children: React.ReactElement): React.ReactElement {
  const { disabled } = children.props as { disabled?: boolean };
  if (!disabled) {
    return children;
  }
  return (
    <span tabIndex={0} className="inline-flex cursor-not-allowed [&>*]:pointer-events-none">
      {children}
    </span>
  );
}

export function Tooltip({
  content,
  children,
  side = 'top',
  align = 'center',
  disabled = false,
  open,
  defaultOpen,
  onOpenChange,
  contentClassName,
}: TooltipProps) {
  const hasProvider = React.useContext(HasProviderContext);
  const trigger = useTriggerElement(children);

  const tooltip = (
    <TooltipPrimitive.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      <TooltipPrimitive.Trigger asChild>{trigger}</TooltipPrimitive.Trigger>
      {!disabled && (
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            align={align}
            // Radix measures to the bubble, so the arrow's own height has to be
            // added for the 4px of §3 to land at the arrow TIP.
            sideOffset={TRIGGER_GAP + ARROW_HEIGHT}
            style={BUBBLE_STYLE}
            className={cn(BUBBLE_CLASS, contentClassName)}
          >
            {content}
            <TooltipPrimitive.Arrow width={ARROW_WIDTH} height={ARROW_HEIGHT} style={ARROW_STYLE} />
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      )}
    </TooltipPrimitive.Root>
  );

  // `disableHoverableContent` stays at Radix's `false`: turning it off would
  // break WCAG 1.4.13, which requires hover content to stay reachable.
  return hasProvider ? (
    tooltip
  ) : (
    <TooltipProvider>{tooltip}</TooltipProvider>
  );
}
