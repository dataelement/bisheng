import * as React from 'react';
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';
import cn from '../../utils/cn';
import { Tooltip } from '../Tooltip';

/**
 * Segmented — design-system base component (组件-Segmented分段控制器.md v1.6).
 *
 * Switches HOW the same content is shown — list vs cards, day vs week — and
 * applies IMMEDIATELY. Navigation between content blocks is Tabs; a choice
 * that travels with a form is a Radio (判别表 in the spec §1). Semantically a
 * radio group (§落地 2): `role="radiogroup"` / `role="radio"`, arrow keys move
 * AND select. Baked in per spec: translucent neutral track and one
 * floating thumb, no shadow (§2); 3px track inset with concentric radii;
 * content-sized segments, `block` fills the container with equal widths (§2);
 * three sizes 28/32/36 — medium sits on the control ladder, small/large pull
 * in half a step (§3), all using 14px text; selection uses brand text in light
 * and a translucent brand fill with primary text in dark; only dark selection
 * raises the font weight to 500 (§5);
 * 200ms thumb slide; the gray keyboard-only
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
  small: 'h-7 rounded-md text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  medium: 'h-8 rounded-lg text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  large: 'h-9 rounded-lg text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
};

/** §4 — segment padding 8/12/20, icon 14/16/18 with 8px gap (4px on small). */
const SEGMENT_SIZE: Record<SegmentedSize, string> = {
  small: 'gap-1 px-2 [&_svg]:size-3.5',
  medium: 'gap-2 px-3 [&_svg]:size-4',
  large: 'gap-2 px-5 [&_svg]:size-[18px]',
};

/** §2 — thumb radius = outer radius − 3px inset (concentric nesting). */
const THUMB_RADIUS: Record<SegmentedSize, string> = {
  small: 'rounded-[3px]',
  medium: 'rounded-[5px]',
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
    const trackRef = React.useRef<HTMLDivElement | null>(null);
    const segmentRefs = React.useRef(new Map<string, HTMLButtonElement>());
    const handleTrackRef = React.useCallback((node: HTMLDivElement | null) => {
      trackRef.current = node;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    }, [ref]);
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
    const activeDisabled = disabled || items.find((option) => option.value === current)?.disabled;
    const [thumb, setThumb] = React.useState<{ left: number; width: number } | null>(null);

    React.useLayoutEffect(() => {
      const track = trackRef.current;
      const measure = () => {
        const active = current != null ? segmentRefs.current.get(current) : undefined;
        const next = active ? { left: active.offsetLeft, width: active.offsetWidth } : null;
        setThumb((previous) =>
          previous?.left === next?.left && previous?.width === next?.width ? previous : next,
        );
      };
      measure();
      // Any segment can move the selected one when its content width changes.
      // Observe all segments as well as the track for fonts and container resizes.
      const observer = new ResizeObserver(measure);
      if (track) observer.observe(track);
      segmentRefs.current.forEach((segment) => observer.observe(segment));
      return () => observer.disconnect();
    }, [current, items, size, block]);

    const handleChange = (next: string) => {
      setInnerValue(next);
      onChange?.(next);
    };

    return (
      <RadioGroupPrimitive.Root
        ref={handleTrackRef}
        orientation="horizontal"
        value={current}
        onValueChange={handleChange}
        disabled={disabled}
        className={cn(
          // §2 — hug each segment's content; only block uses equal columns.
          // `relative` anchors the measured sliding thumb.
          'relative grid-flow-col select-none bg-text-1/[0.04] p-[3px] font-normal dark:bg-text-1/[0.08]',
          block ? 'grid w-full auto-cols-fr' : 'inline-grid auto-cols-max',
          // §5 — keyboard-only gray ring around the WHOLE control (2px gray-2,
          // same as the input focus ring).
          'has-[:focus-visible]:shadow-focus',
          TRACK_SIZE[size],
          className,
        )}
        {...props}
      >
        {/* §2/§5 — one thumb follows the selected segment's measured geometry.
            Dark mode uses a translucent brand fill, with a muted fill when disabled. */}
        {thumb && (
          <span
            aria-hidden
            className={cn(
              'absolute bottom-[3px] left-0 top-[3px] bg-bg-page transition-[transform,width,background-color] duration-200',
              activeDisabled ? 'dark:bg-btn-disabled-bg' : 'dark:bg-blue-500/20',
              THUMB_RADIUS[size],
            )}
            style={{
              width: thumb.width,
              transform: `translateX(${thumb.left}px)`,
            }}
          />
        )}
        {items.map((option) => {
          const segment = (
            <RadioGroupPrimitive.Item
              key={option.value}
              value={option.value}
              ref={(node) => {
                if (node) segmentRefs.current.set(option.value, node);
                else segmentRefs.current.delete(option.value);
              }}
              disabled={option.disabled}
              // §4 — an icon-only segment still needs an accessible name.
              aria-label={option.label === undefined ? option.tooltip : undefined}
              className={cn(
                // z-index lifts the label above the thumb; btn-touch-hit is the
                // ≥44px touch hot zone (§6), anchored by `relative`.
                'btn-touch-hit relative z-[1] inline-flex cursor-pointer items-center justify-center whitespace-nowrap outline-none transition-colors',
                // §5 — brand text in light, primary text over the translucent brand fill in dark.
                // Hover uses brand text; only dark selection raises the weight to 500.
                // Disabled items keep the disabled color and normal weight.
                // Tooltip owns data-state on icon-only triggers; aria-checked stays the selection source.
                'text-text-3 hover:text-blue-500 enabled:aria-checked:text-blue-500 dark:enabled:aria-checked:text-text-1 dark:enabled:aria-checked:font-medium',
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
