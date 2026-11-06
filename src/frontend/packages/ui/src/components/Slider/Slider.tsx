import * as React from 'react';
import * as SliderPrimitive from '@radix-ui/react-slider';
import cn from '../../utils/cn';
import { InputNumber, type InputNumberProps } from '../InputNumber';
import { Tooltip } from '../Tooltip';
import {
  adjacentMark,
  inBoundsLeft,
  nearestMark,
  normalizeMarks,
  toPercent,
  type SliderMarks,
} from './marks';

/**
 * Slider — a rough value inside a bounded range, with live feedback while
 * dragging (组件-Slider滑块.md v1): volume, opacity, a model's temperature.
 *
 * What the component pins down: ONE size (4px track, 16px thumb → 18px on
 * hover / drag, 8px marks — §4), the white thumb with a brand ring (§2), the
 * range form whose thumbs never cross (§3.2), marks with in-bounds labels and
 * optional snapping (§3.3), and the either-or value display (§5): a number
 * box beside it, or a tooltip bubble — never both.
 *
 * Save / request in `onValueCommit` (pointer up, key up), not in
 * `onValueChange` — that one fires on every pixel of a drag (§6).
 *
 * Not this component: a range too wide to drag precisely (1～10000) or too
 * narrow to be worth dragging (1～3) — use InputNumber / Radio / Segmented.
 */
export type SliderValue = number | [number, number];

export interface SliderProps {
  /** A number = single thumb; a pair = range (§3.2). Shape of the callbacks follows it. */
  value?: SliderValue;
  defaultValue?: SliderValue;
  /** Fires live while dragging — preview only. */
  onValueChange?: (value: SliderValue) => void;
  /** Fires once on release / key up — the place for saves and requests (§6). */
  onValueCommit?: (value: SliderValue) => void;
  min?: number;
  max?: number;
  step?: number;
  /** §3.3 — values to mark under the track; a record also gives each label. */
  marks?: SliderMarks;
  /** §3.3 — only the marks are valid stops (playback speed); `step` is ignored. */
  snapToMarks?: boolean;
  /**
   * §5 — `tooltip` (default): a bubble on hover / drag / keyboard focus, for
   * "just see the effect" values. `input`: a number box beside the track
   * (two for a range), for values that must be read back exactly.
   */
  valueDisplay?: 'tooltip' | 'input';
  /** Formats the bubble and the default mark labels (「70%」「1.5x」). */
  formatValue?: (value: number) => React.ReactNode;
  /** Passed to the number box(es) in `input` mode — unit suffix, stepper labels, error copy. The box is always `small` (§5.1). */
  inputProps?: Omit<InputNumberProps, 'value' | 'defaultValue' | 'onChange' | 'min' | 'max' | 'step' | 'disabled' | 'size'>;
  disabled?: boolean;
  /** Accessible name of the thumb(s); a pair for a range (lower, upper). */
  thumbLabel?: string | [string, string];
  name?: string;
  className?: string;
}

const toArray = (value: SliderValue | undefined, fallback: number): number[] =>
  value === undefined ? [fallback] : Array.isArray(value) ? [...value] : [value];

const decimalsOf = (n: number) => (String(n).split('.')[1] ?? '').length;

/** §2/§7 — the 16px thumb; 18px under the pointer or while dragged. */
const THUMB_CLASS =
  'slider-thumb-hit relative block size-4 rounded-full border-2 border-blue-500 bg-bg-page outline-none transition-[transform,box-shadow] duration-150 ' +
  'cursor-grab hover:scale-[1.125] data-[dragging]:scale-[1.125] data-[dragging]:cursor-grabbing focus-visible:shadow-focus ' +
  'data-[disabled]:cursor-not-allowed data-[disabled]:border-border-deep data-[disabled]:hover:scale-100';

export const Slider = React.forwardRef<HTMLSpanElement, SliderProps>(function Slider(
  {
    value,
    defaultValue,
    onValueChange,
    onValueCommit,
    min = 0,
    max = 100,
    step = 1,
    marks: marksProp,
    snapToMarks = false,
    valueDisplay = 'tooltip',
    formatValue,
    inputProps,
    disabled = false,
    thumbLabel,
    name,
    className,
  },
  ref,
) {
  const isRange = Array.isArray(value ?? defaultValue);
  const marks = React.useMemo(() => normalizeMarks(marksProp, min, max), [marksProp, min, max]);
  const snapping = snapToMarks && marks.length > 0;

  // What Radix draws. In snap mode it moves freely during a drag and lands on
  // a mark on release (§3.3「松手吸附」), so it can differ from the emitted value.
  const [raw, setRaw] = React.useState<number[]>(() => toArray(value ?? defaultValue, min));
  const snap = React.useCallback(
    (values: number[]) => (snapping ? values.map((v) => nearestMark(v, marks)) : values),
    [snapping, marks],
  );
  const emitted = React.useRef<number[]>(snap(raw));

  // A controlled value set from outside replaces the thumbs — unless it is the
  // value they already stand for (a snap-mode drag between two marks).
  const controlledKey = value === undefined ? null : toArray(value, min).join(',');
  React.useEffect(() => {
    if (controlledKey === null) return;
    const next = controlledKey.split(',').map(Number);
    if (snap(raw).join(',') === controlledKey) return;
    emitted.current = next;
    setRaw(next);
    // `raw` is read, not tracked: only an outside change of `value` should sync.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [controlledKey, snap]);

  const shape = (values: number[]): SliderValue =>
    isRange ? [values[0], values[1] ?? values[0]] : values[0];

  const update = (values: number[]) => {
    setRaw(values);
    const next = snap(values);
    if (next.join(',') === emitted.current.join(',')) return;
    emitted.current = next;
    onValueChange?.(shape(next));
  };

  const commit = (values: number[]) => {
    const next = snap(values);
    setRaw(next);
    emitted.current = next;
    onValueCommit?.(shape(next));
  };

  // ---- thumb states: hover, drag and keyboard focus drive the bubble (§5.2) ----
  const [hovered, setHovered] = React.useState<number | null>(null);
  const [focusVisible, setFocusVisible] = React.useState<number | null>(null);
  const [active, setActive] = React.useState<number | null>(null);
  const [dragging, setDragging] = React.useState(false);

  React.useEffect(() => {
    if (!dragging) return;
    const stop = () => setDragging(false);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    return () => {
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
  }, [dragging]);

  // Snap mode: arrows walk mark to mark; Radix's own step would stay on one mark.
  const handleThumbKeyDown = (index: number) => (event: React.KeyboardEvent) => {
    if (!snapping || disabled) return;
    const forward = event.key === 'ArrowRight' || event.key === 'ArrowUp';
    const back = event.key === 'ArrowLeft' || event.key === 'ArrowDown';
    if (!forward && !back) return;
    event.preventDefault();
    event.stopPropagation();
    const next = [...raw];
    next[index] = adjacentMark(raw[index], forward ? 1 : -1, marks);
    if (isRange) {
      // §3.2 — the thumbs may meet but never cross.
      if (index === 0) next[0] = Math.min(next[0], raw[1]);
      else next[1] = Math.max(next[1], raw[0]);
    }
    update(next);
    commit(next);
  };

  const shown = snap(raw);
  const format = (v: number) => (formatValue ? formatValue(v) : v);
  const labels = Array.isArray(thumbLabel) ? thumbLabel : [thumbLabel, thumbLabel];
  // Snap mode drags freely (fine step) and lands on release.
  const radixStep = snapping ? (max - min) / 1000 : step;

  const slider = (
    <SliderPrimitive.Root
      ref={ref}
      name={name}
      min={min}
      max={max}
      step={radixStep}
      value={raw}
      minStepsBetweenThumbs={0}
      disabled={disabled}
      onValueChange={update}
      onValueCommit={commit}
      onPointerDown={() => {
        if (!disabled) setDragging(true);
      }}
      className={cn(
        // §2 — 32px tall so it lines up with medium inputs and buttons; §4 — ≥120px wide.
        'relative flex h-8 w-full min-w-[120px] touch-none select-none items-center',
        disabled && 'cursor-not-allowed',
      )}
    >
      <SliderPrimitive.Track className="slider-track-hit relative h-1 w-full grow rounded-full bg-fill-3">
        <SliderPrimitive.Range
          className={cn('absolute h-full rounded-full', disabled ? 'bg-fill-4' : 'bg-blue-500')}
        />
      </SliderPrimitive.Track>
      {marks.map((mark) => {
        const covered = isRange
          ? mark.value >= shown[0] && mark.value <= shown[1]
          : mark.value <= shown[0];
        return (
          <span
            key={mark.value}
            aria-hidden
            className={cn(
              'pointer-events-none absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-bg-page',
              covered && !disabled ? 'border-blue-500' : covered ? 'border-fill-4' : 'border-border-base',
            )}
            style={{ left: inBoundsLeft(toPercent(mark.value, min, max)) }}
          />
        );
      })}
      {raw.map((v, index) => {
        const thumb = (
          <SliderPrimitive.Thumb
            key={index}
            aria-label={labels[index]}
            data-dragging={dragging && active === index ? '' : undefined}
            className={THUMB_CLASS}
            onPointerEnter={() => setHovered(index)}
            onPointerLeave={() => setHovered((h) => (h === index ? null : h))}
            onFocus={(event) => {
              setActive(index);
              if (event.currentTarget.matches(':focus-visible')) setFocusVisible(index);
            }}
            onBlur={() => setFocusVisible((f) => (f === index ? null : f))}
            onKeyDown={handleThumbKeyDown(index)}
          />
        );
        if (valueDisplay !== 'tooltip') return thumb;
        const open =
          !disabled && (hovered === index || focusVisible === index || (dragging && active === index));
        return (
          <Tooltip key={index} content={format(snapping ? nearestMark(v, marks) : v)} open={open}>
            {thumb}
          </Tooltip>
        );
      })}
    </SliderPrimitive.Root>
  );

  const withMarks = marks.length > 0 && (
    <div className="flex w-full min-w-[120px] flex-col">
      {slider}
      {/* §3.3 — labels under their marks; the two ends align with the track ends. */}
      <div className="relative h-5">
        {marks.map((mark) => {
          const percent = toPercent(mark.value, min, max);
          const edge = percent === 0 ? 'left-0' : percent === 100 ? 'right-0' : '-translate-x-1/2';
          return (
            <span
              key={mark.value}
              className={cn('absolute top-0 whitespace-nowrap text-caption text-text-3', edge)}
              style={percent === 0 || percent === 100 ? undefined : { left: inBoundsLeft(percent) }}
            >
              {mark.label ?? format(mark.value)}
            </span>
          );
        })}
      </div>
    </div>
  );

  const track = withMarks || slider;
  if (valueDisplay !== 'input') return <div className={cn('w-full', className)}>{track}</div>;

  // §5.1 — the box takes the width its largest value needs (InputNumber §3).
  const precision = snapping ? Math.max(...marks.map((m) => decimalsOf(m.value))) : decimalsOf(step);
  const chars = Math.max(String(Math.trunc(max)).length, String(Math.trunc(min)).length) + (precision ? precision + 1 : 0);
  // 40px = small row padding + stepper column + border; a unit suffix adds its
  // own padding plus about one CJK glyph — without it the digits get squeezed to 0.
  const chrome = inputProps?.suffix !== undefined ? 68 : 40;
  const boxStyle = { width: `calc(${chars}ch + ${chrome}px)` };

  // §5.1 — a valid number moves the thumb; an invalid one leaves it on the last
  // valid value (the box reports the error itself).
  const handleBoxChange = (index: number) => (next: number | null, detail: { error: unknown }) => {
    if (next === null || detail.error) return;
    const values = [...shown];
    values[index] = next;
    update(values);
    commit(values);
  };

  // §5.1 — the box beside a slider is the small (24px) size, centred on the
  // 32px slider row so it lines up with the track even when labels hang below.
  const box = (index: number) => (
    <div className="flex h-8 shrink-0 items-center" style={boxStyle}>
      <InputNumber
        {...inputProps}
        size="small"
        value={shown[index]}
        min={isRange && index === 1 ? shown[0] : min}
        max={isRange && index === 0 ? shown[1] : max}
        step={snapping ? undefined : step}
        precision={precision}
        disabled={disabled}
        onChange={handleBoxChange(index)}
      />
    </div>
  );

  return (
    // §5 — 16px between the track and its box(es); a range gets one on each side.
    <div className={cn('flex w-full items-start gap-4', className)}>
      {isRange && box(0)}
      <div className="min-w-[120px] flex-1">{track}</div>
      {box(isRange ? 1 : 0)}
    </div>
  );
});
