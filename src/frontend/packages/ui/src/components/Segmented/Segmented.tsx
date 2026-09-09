import * as React from 'react';
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';
import cn from '../../utils/cn';
import { Tooltip } from '../Tooltip';

/**
 * Segmented — design-system base component (组件-Segmented分段控制器.md v1).
 *
 * Switches HOW the same content is shown — list vs cards, day vs week — and
 * applies IMMEDIATELY. Navigation between content blocks is Tabs; a choice
 * that travels with a form is a Radio (判别表 in the spec §1). Semantically a
 * radio group (§落地 2): `role="radiogroup"` / `role="radio"`, arrow keys move
 * AND select. Baked in per spec: gray track (fill-2) with a floating
 * page-colored thumb, no shadow (§2); 3px track inset with concentric radii;
 * equal-width segments sized by the widest, `block` fills the container (§2);
 * three sizes 28/32/36 — medium sits on the control ladder, small/large pull
 * in half a step (§3); selection never uses brand color, selected weight 500
 * over unselected 400 (§5); 200ms thumb slide; the gray keyboard-only
 * focus ring around the whole control; ≥44px touch hot zones (§6). Always has
 * a selected segment — with no `value`/`defaultValue` the first enabled
 * option is selected (§1).
 */

export type SegmentedSize = 'small' | 'medium' | 'large';

export interface SegmentedOption {
  value: string;
  /** Text (2–4 chars per §4) and/or nothing for icon-only segments. */
  label?: React.ReactNode;
  /** Rides the 14/16/18 icon ladder; 8px gap to the text, 4px on small (§4). */
  icon?: React.ReactNode;
  /**
   * §4 — icon-only segments MUST explain themselves: plain-text tooltip,
   * doubling as the `aria-label` when there is no text label.
   */
  tooltip?: string;
  /** §5 — this segment grays out and skips; the others stay clickable. */
  disabled?: boolean;
}

/** §3 — track height / outer radius / per-segment padding, 28/32/36 ladder.
 * Font sizes reference the PRIMITIVE scale vars (control text must not follow
 * the ≤768px body remap — same rationale as Button §3). */
const TRACK_SIZE: Record<SegmentedSize, string> = {
  small: 'h-7 rounded text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  medium: 'h-8 rounded-md text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  large: 'h-9 rounded-lg text-[length:var(--font-size-4)] leading-[var(--line-height-4)]',
};

/** §4 — segment padding 8/12/16, icon 14/16/18 with 8px gap (4px on small). */
const SEGMENT_SIZE: Record<SegmentedSize, string> = {
  small: 'gap-1 px-2 [&_svg]:size-3.5',
  medium: 'gap-2 px-3 [&_svg]:size-4',
  large: 'gap-2 px-4 [&_svg]:size-[18px]',
};

/** §2 — thumb radius = outer radius − 3px inset (concentric nesting). */
const THUMB_RADIUS: Record<SegmentedSize, string> = {
  small: 'rounded-[1px]',
  medium: 'rounded-[3px]',
  large: 'rounded-[5px]',
};

export interface SegmentedProps
  extends Omit<
    React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>,
    'onChange' | 'onValueChange' | 'orientation' | 'dir' | 'loop' | 'asChild'
  > {
  /** 2–5 segments (§1); a bare string is shorthand for `{ value, label }`. */
  options: (SegmentedOption | string)[];
  /** §3 — 28/32/36; medium matches the 32px controls sitting beside it. */
  size?: SegmentedSize;
  /** §2 — fill the parent, segments split the width evenly (窄屏首选, §6). */
  block?: boolean;
  onChange?: (value: string) => void;
}

const Segmented = React.forwardRef<HTMLDivElement, SegmentedProps>(
  (
    { options, size = 'medium', block = false, value, defaultValue, onChange, disabled, className, ...props },
    ref,
  ) => {
    const items = React.useMemo(
      () => options.map((o) => (typeof o === 'string' ? ({ value: o, label: o } as SegmentedOption) : o)),
      [options],
    );

    // §1 — "always one selected": uncontrolled with no defaultValue starts on
    // the first enabled segment. The current value is mirrored locally so the
    // thumb knows which segment to sit on in both modes.
    const fallback = defaultValue ?? items.find((o) => !o.disabled)?.value;
    const [innerValue, setInnerValue] = React.useState(fallback);
    const current = value !== undefined ? value : innerValue;
    const activeIndex = items.findIndex((o) => o.value === current);

    const handleChange = (next: string) => {
      setInnerValue(next);
      onChange?.(next);
    };

    return (
      <RadioGroupPrimitive.Root
        ref={ref}
        orientation="horizontal"
        value={current}
        onValueChange={handleChange}
        disabled={disabled}
        className={cn(
          // §2 — equal-width segments, all sized by the widest (auto-cols-fr on
          // a content-sized grid); `relative` anchors the sliding thumb.
          'relative grid-flow-col auto-cols-fr select-none bg-fill-2 p-[3px] font-normal',
          block ? 'grid w-full' : 'inline-grid',
          // §5 — keyboard-only gray ring around the WHOLE control (2px gray-2,
          // same as the input focus ring).
          'has-[:focus-visible]:shadow-focus',
          TRACK_SIZE[size],
          className,
        )}
        {...props}
      >
        {/* §2/§5 — the floating thumb: one absolute element sliding 200ms to
            the selected segment. Equal columns make its geometry pure CSS —
            width = one column, translateX = index × own width. Light: the
            spec's white block = bg-bg-page. Dark: elevation LIGHTENS on
            #121212 (same direction as the button fills), so the page color
            would sink BELOW the track — float it two ramp steps above fill-2
            instead (fill-4, the iOS dark-segmented contrast). */}
        {activeIndex >= 0 && (
          <span
            aria-hidden
            className={cn(
              'absolute bottom-[3px] left-[3px] top-[3px] bg-bg-page transition-transform duration-200 dark:bg-fill-4',
              THUMB_RADIUS[size],
            )}
            style={{
              width: `calc((100% - 6px) / ${items.length})`,
              transform: `translateX(${activeIndex * 100}%)`,
            }}
          />
        )}
        {items.map((option) => {
          const segment = (
            <RadioGroupPrimitive.Item
              key={option.value}
              value={option.value}
              disabled={option.disabled}
              // §4 — an icon-only segment still needs an accessible name.
              aria-label={option.label === undefined ? option.tooltip : undefined}
              className={cn(
                // z-index lifts the label above the thumb; btn-touch-hit is the
                // ≥44px touch hot zone (§6), anchored by `relative`.
                'btn-touch-hit relative z-[1] inline-flex cursor-pointer items-center justify-center whitespace-nowrap outline-none transition-colors',
                // §5 — selected text-1 at weight 500 on the thumb, unselected
                // text-3 at 400, hover deepens to text-1 (background
                // untouched). CJK glyphs keep their advance across weights and
                // labels are 2–4 chars (§4), so the bolder selected segment
                // does not widen the equal-width columns.
                'text-text-3 hover:text-text-1 data-[state=checked]:font-medium data-[state=checked]:text-text-1',
                'disabled:cursor-not-allowed disabled:text-btn-disabled-text',
                SEGMENT_SIZE[size],
              )}
            >
              {option.icon}
              {option.label}
            </RadioGroupPrimitive.Item>
          );
          return option.tooltip ? (
            <Tooltip key={option.value} content={option.tooltip}>
              {segment}
            </Tooltip>
          ) : (
            segment
          );
        })}
      </RadioGroupPrimitive.Root>
    );
  },
);
Segmented.displayName = 'Segmented';

export { Segmented };
