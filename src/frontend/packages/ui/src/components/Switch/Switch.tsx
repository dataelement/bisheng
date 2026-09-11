import * as React from 'react';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';

/**
 * Switch — design-system base component (组件-Switch开关.md v1).
 *
 * Flips ONE standalone setting and applies IMMEDIATELY — a choice that travels
 * with a form is a Checkbox/Radio. Baked in per spec: two sizes 22×38 / 18×32
 * with a full-radius track, round thumb and 2px inset (§2); brand track on /
 * gray track off with one-step-deeper hovers (§4); disabled keeps the side it
 * stopped on at 40% opacity (§4 — a uniform gray would hide WHICH side);
 * loading locks the toggle with a spinner in the thumb; the keyboard-only gray
 * focus ring; and the ≥44px touch hot zone (§5). On async failure the CALLER
 * flips `checked` back and explains via toast (§4 — 失败要回弹).
 */

export type SwitchSize = 'default' | 'small';

/** §2 — track height × min width (widens with inner text, min stays).
 * 22×38 / 18×32, not antd's 22×44 / 16×28: the designer called 2:1 too wide
 * (2026-08-25, referencing the chat tools switch at 20×34 ≈ 1.7:1). */
const TRACK_SIZE: Record<SwitchSize, string> = {
  default: 'h-[22px] min-w-[38px]',
  small: 'h-[18px] min-w-8',
};

/** §2 — thumb 18/14 with a 2px inset; spinner rides the icon ladder (落地 §3). */
const THUMB_SIZE: Record<SwitchSize, string> = {
  default: 'size-[18px] [&_svg]:size-3.5',
  small: 'size-3.5 [&_svg]:size-2.5',
};

/** §3 — inner text: 12px white, sitting on the side the thumb vacated. */
const INNER_TEXT = 'select-none text-[length:var(--font-size-1)] leading-none text-white';

export interface SwitchProps
  extends Omit<React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>, 'asChild'> {
  /** §2 — `default` 22×44 (aligns with the 22px body line); `small` 16×28. */
  size?: SwitchSize;
  /**
   * §4 — waiting for the server to confirm: spinner in the thumb, toggle
   * locked. The visual state stays where the user put it; on failure the
   * caller flips `checked` back and explains with a toast.
   */
  loading?: boolean;
  /** §3 — optional emphasis inside the track, ≤2 characters or one icon; shown while ON. */
  checkedChildren?: React.ReactNode;
  /** §3 — counterpart shown while OFF. `small` has no room and renders neither. */
  unCheckedChildren?: React.ReactNode;
}

const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  (
    { size = 'default', loading = false, disabled, checkedChildren, unCheckedChildren, className, ...props },
    ref,
  ) => {
    // §3 — small cannot fit inner text, so it never renders any.
    const showInner = size === 'default';
    return (
      <SwitchPrimitive.Root
        ref={ref}
        disabled={disabled || loading}
        // §4 — the 40% opacity is invisible to a screen reader (落地 §4).
        aria-disabled={disabled || loading || undefined}
        className={cn(
          'group/track btn-touch-hit relative inline-flex shrink-0 cursor-pointer items-center rounded-full outline-none transition-colors',
          // §4 — off: gray track (switch-off = gray-4, hover gray-5); on: brand
          // track, hover one step lighter (same source as Button primary hover).
          'bg-switch-off enabled:hover:bg-switch-off-hover data-[state=checked]:bg-blue-500 data-[state=checked]:enabled:hover:bg-blue-400',
          'focus-visible:shadow-focus',
          TRACK_SIZE[size],
          disabled && 'cursor-not-allowed opacity-40',
          loading && !disabled && 'cursor-default',
          className,
        )}
        {...props}
      >
        {showInner && unCheckedChildren !== undefined && (
          <span className={cn(INNER_TEXT, 'ml-[22px] mr-1.5 group-data-[state=checked]/track:hidden')}>
            {unCheckedChildren}
          </span>
        )}
        {showInner && checkedChildren !== undefined && (
          <span className={cn(INNER_TEXT, 'ml-1.5 mr-[22px] hidden group-data-[state=checked]/track:inline')}>
            {checkedChildren}
          </span>
        )}
        {/* §2 — the thumb travels edge to edge with the 2px inset; `left` +
            transform track a text-widened track without hardcoding a distance.
            0.2s per 落地 §3. Fixed white: the track carries the color. */}
        <SwitchPrimitive.Thumb
          className={cn(
            'absolute left-0.5 top-1/2 flex -translate-y-1/2 items-center justify-center rounded-full bg-white transition-all duration-200 data-[state=checked]:left-[calc(100%-2px)] data-[state=checked]:-translate-x-full',
            THUMB_SIZE[size],
          )}
        >
          {loading && <Outlined.Loading className="animate-spin text-text-3" />}
        </SwitchPrimitive.Thumb>
      </SwitchPrimitive.Root>
    );
  },
);
Switch.displayName = 'Switch';

export { Switch };
