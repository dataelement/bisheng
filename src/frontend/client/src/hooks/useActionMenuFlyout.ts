import { useCallback, useEffect, useRef, useState, type PointerEvent } from 'react';
import { getDisplayScale, getRectScale, getRectViewport } from '~/utils/fontSize';

/** Inner padding of an action-menu surface (`p-2`), in CSS pixels. */
const SURFACE_PADDING = 8;
/** Gap kept between a flyout and the window edge, in CSS pixels. */
const WINDOW_INSET = 8;
/**
 * How long the flyout survives after the cursor has left both the trigger and
 * the flyout itself. Long enough to cross the gap between them at a human
 * mouse speed, short enough not to feel stuck.
 */
const CLOSE_DELAY_MS = 250;

/** Placement props handed to Radix; empty means "keep the library's own". */
interface FlyoutPlacement {
  alignOffset?: number;
  avoidCollisions?: boolean;
}

interface UseActionMenuFlyoutOptions {
  /** Rows the flyout renders — its height is derived from this. */
  rowCount: number;
  /** Open state of the menu the trigger lives in; closing it resets the flyout. */
  parentOpen: boolean;
}

/**
 * Hover behaviour and placement for a submenu ("flyout") hanging off an action
 * menu row, for the case where the page is under a whole-page zoom.
 *
 * Two things go wrong with the stock Radix submenu once `zoom` is in play, and
 * this hook takes both away from it:
 *
 * 1. Staying open while the cursor travels to the flyout is decided by a "grace
 *    area" polygon that Radix builds from the flyout's getBoundingClientRect()
 *    and then tests the pointer's clientX/clientY against. Those two are the
 *    same coordinate space only while the page is unzoomed: the embedded
 *    browsers this ships to report rects in pre-zoom CSS pixels but events in
 *    physical ones, so the polygon sits somewhere the cursor never visits and
 *    the flyout closes the moment the cursor leaves the trigger. Whether it
 *    happens on a given trip depends on the path taken, which is what makes it
 *    look intermittent. Plain pointerenter / pointerleave containment carries no
 *    coordinates at all, so it holds on every engine.
 *
 * 2. Collision handling has the same disease — Radix compares those rects
 *    against a window measured in physical pixels — so under a zoom it is
 *    turned off and the lift a bottom-anchored flyout needs is computed here
 *    instead, from the trigger's own rect and a window converted into the
 *    rect's units. Deriving it rather than hardcoding it matters: the number
 *    depends on where the row sits in the menu, and rows above it come and go
 *    (the storage card renders nothing until its quota arrives, and taller when
 *    the quota is finite).
 *
 * Point 1 applies at every level, point 2 only while a zoom is active — an
 * unzoomed page keeps the library's placement exactly as it is today.
 */
export function useActionMenuFlyout({ rowCount, parentOpen }: UseActionMenuFlyoutOptions) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<FlyoutPlacement>({});
  const triggerRef = useRef<HTMLDivElement>(null);
  /** Cursor containment, tracked as booleans so no coordinate math is involved. */
  const hoverRef = useRef({ trigger: false, content: false });
  const closeTimerRef = useRef(0);

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = 0;
    }
  }, []);

  const scheduleClose = useCallback(() => {
    clearCloseTimer();
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = 0;
      if (!hoverRef.current.trigger && !hoverRef.current.content) {
        setOpen(false);
      }
    }, CLOSE_DELAY_MS);
  }, [clearCloseTimer]);

  useEffect(() => clearCloseTimer, [clearCloseTimer]);

  // The menu closing does not take the flyout's state with it — the hook lives
  // on outside both — so reset it here or the flyout reappears on next open.
  useEffect(() => {
    if (!parentOpen) {
      clearCloseTimer();
      hoverRef.current = { trigger: false, content: false };
      setOpen(false);
    }
  }, [parentOpen, clearCloseTimer]);

  /**
   * How far the flyout has to be lifted so its last row stays inside the
   * window, in the units Radix reads alignOffset in. Never positive: a flyout
   * that already fits keeps its top aligned with its trigger, which is the one
   * placement where a straight sideways move never crosses another row.
   *
   * Only taken over while a page zoom is active. Unzoomed, rects and the window
   * are quoted in the same space and the library's own collision handling is
   * correct — including the sideways flip this one does not attempt — so it is
   * left alone rather than replaced with a second opinion.
   */
  const measurePlacement = useCallback((): FlyoutPlacement => {
    const el = triggerRef.current;
    if (!el || getDisplayScale() === 1) return {};
    const rect = el.getBoundingClientRect();
    if (rect.height === 0) return {};
    const rectScale = getRectScale();
    // Row height comes off the trigger, which wears the same row class as the
    // flyout's own rows — so this follows any future row-height change, and
    // arrives already expressed in the rect's units.
    const flyoutHeight = rowCount * rect.height + 2 * SURFACE_PADDING * rectScale;
    const roomBelowTop = getRectViewport().height - WINDOW_INSET * rectScale - rect.top;
    return {
      alignOffset: Math.min(0, Math.round(roomBelowTop - flyoutHeight)),
      avoidCollisions: false,
    };
  }, [rowCount]);

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (next) {
        clearCloseTimer();
        setPlacement(measurePlacement());
        setOpen(true);
        return;
      }
      // Radix asks to close as soon as its own pointer bookkeeping says the
      // cursor left — see (1) above for why that bookkeeping cannot be trusted
      // here. While the cursor is demonstrably still on the trigger or in the
      // flyout, ignore it; scheduleClose is what actually closes them.
      if (hoverRef.current.trigger || hoverRef.current.content) return;
      clearCloseTimer();
      setOpen(false);
    },
    [clearCloseTimer, measurePlacement],
  );

  const track = useCallback(
    (part: 'trigger' | 'content', entering: boolean) => (event: PointerEvent) => {
      // Touch has no hover; leave those interactions on Radix's own click path.
      if (event.pointerType !== 'mouse') return;
      hoverRef.current[part] = entering;
      if (entering) {
        clearCloseTimer();
      } else {
        scheduleClose();
      }
    },
    [clearCloseTimer, scheduleClose],
  );

  return {
    /** Spread on `DropdownMenuSub`. */
    subProps: { open, onOpenChange: handleOpenChange },
    /** Spread on `DropdownMenuSubTrigger`. */
    triggerProps: {
      ref: triggerRef,
      onPointerEnter: track('trigger', true),
      onPointerLeave: track('trigger', false),
    },
    /** Spread on `DropdownMenuSubContent`. */
    contentProps: {
      ...placement,
      onPointerEnter: track('content', true),
      onPointerLeave: track('content', false),
    },
  };
}
