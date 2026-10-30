import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import {
  CONTROL_ROW,
  FIELD_BASE,
  assignRef,
  focusFieldFromShell,
  resolveState,
  shellStyles,
  type InputSize,
  type InputStatus,
} from '../Input/shared';
import {
  countDecimals,
  formatValue,
  parseText,
  sanitizeInput,
  stepValue,
  validate,
  type InputNumberError,
} from './numberUtils';

/**
 * InputNumber — one number that will be computed with: a count, a ratio, a
 * duration, a threshold (组件-InputNumber数字输入框.md v1).
 *
 * The shell is the Input shell verbatim (§2: sizes, radius, focus chain, the
 * four states), plus a 20px stepper column on the right that only shows on
 * hover — its slot is always reserved so the digits never jump (§2.1).
 *
 * What the component pins down: it NEVER rewrites what the user typed (§4.2 —
 * no clamp, no round, empty stays empty); range / precision problems are
 * reported on blur and cleared the moment they are fixed (§5.2「迟报早清」);
 * the wheel does nothing (§2.1); touch hides the steppers (§6).
 *
 * Not this component: digits that are really text (phone, code, ID) — those
 * cannot be added to, use `Input`.
 */
export interface InputNumberProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    'size' | 'prefix' | 'type' | 'value' | 'defaultValue' | 'onChange' | 'min' | 'max' | 'step'
  > {
  /** §3 — the Input ladder (24 / 32 / 40). */
  size?: InputSize;
  /** §5.2 — an outside verdict (form validation). The component's own range / precision error wins over `default`. */
  status?: InputStatus;
  /** Container owns the chrome — same as `Input`. */
  borderless?: boolean;
  /** Controlled value; `null` is「没填」, not 0. */
  value?: number | null;
  defaultValue?: number | null;
  /** §4.1 — set them whenever a bound exists, and say the range in the placeholder or hint. */
  min?: number;
  max?: number;
  /** Default 1; a decimal step also sets the default precision. */
  step?: number;
  /** §4.1 — max decimals; defaults to the step's decimals. Display pads to it (1 → 1.00). */
  precision?: number;
  /**
   * Fires when the parsed number changes. `error` is the CURRENT verdict
   * (shown or not yet) so a form can block submit (§5.2); `null` value = empty.
   */
  onChange?: (value: number | null, detail: { error: InputNumberError | null }) => void;
  /**
   * §5.2 — the hint under the box while an error is shown. Copy comes from the
   * caller (library contract): build「请输入 1～100 之间的数」/「最多保留 2 位小数」
   * from the error's `min` / `max` / `precision`. Omit to render no hint.
   */
  errorMessage?: (error: InputNumberError) => React.ReactNode;
  /** Fires when the SHOWN error changes (after blur, and when it clears). */
  onErrorChange?: (error: InputNumberError | null) => void;
  /** §2 — e.g. a leading icon. */
  prefix?: React.ReactNode;
  /** §2 — the unit (%、秒、条); closes the box, right of the steppers — never inside the value. */
  suffix?: React.ReactNode;
  /** Accessible names of the two steppers — text comes from the caller. */
  increaseLabel?: string;
  decreaseLabel?: string;
  /** Classes for the outer wrapper (width lives here: `className="w-32"`). */
  className?: string;
  /** Classes for the `<input>` itself — rarely needed. */
  inputClassName?: string;
}

/** 落地 5 — first repeat after 300ms, then one step every 100ms. */
const REPEAT_DELAY = 300;
const REPEAT_INTERVAL = 100;

/** §2 — the unit after the stepper column: the row's gap on its left, the row's edge padding on its right. */
const SUFFIX_PADDING: Record<InputSize, string> = {
  small: 'pl-1 pr-[7px]',
  medium: 'pl-2 pr-[11px]',
  large: 'pl-2 pr-[11px]',
};

const STEP_BUTTON =
  'flex flex-1 items-center justify-center text-text-3 outline-none transition-colors hover:bg-fill-1 hover:text-text-2 coarse-pointer:active:bg-fill-2 disabled:cursor-not-allowed disabled:text-text-4 disabled:hover:bg-transparent';

export const InputNumber = React.forwardRef<HTMLInputElement, InputNumberProps>(
  function InputNumber(
    {
      size = 'medium',
      status = 'default',
      borderless = false,
      value,
      defaultValue,
      min,
      max,
      step = 1,
      precision: precisionProp,
      onChange,
      errorMessage,
      onErrorChange,
      prefix,
      suffix,
      increaseLabel,
      decreaseLabel,
      className,
      inputClassName,
      disabled,
      readOnly,
      onBlur,
      onKeyDown,
      ...props
    },
    ref,
  ) {
    const precision = precisionProp ?? countDecimals(step);
    const bounds = { min, max };
    const rules = { min, max, precision };
    const allowNegative = min === undefined || min < 0;
    const isControlled = value !== undefined;

    const fieldRef = React.useRef<HTMLInputElement | null>(null);
    const [text, setText] = React.useState(() => {
      const initial = isControlled ? value : defaultValue;
      return initial === null || initial === undefined ? '' : formatValue(initial, precision);
    });
    // The interval of a held stepper reads this, not the render-time `text`.
    const textRef = React.useRef(text);
    // §5.2「迟报早清」— an error becomes visible on blur, and only clears once fixed.
    const [errorShown, setErrorShown] = React.useState(false);

    const error = validate(text, rules);
    const shownError = errorShown ? error : null;
    const current = parseText(text);
    const state = resolveState(disabled, readOnly);
    const editable = state === 'editable';

    // A controlled value set from outside (a reset, a slider beside the box)
    // replaces the text — unless it is the value the text already says, which
    // keeps a half-typed "1." from snapping back to "1".
    React.useEffect(() => {
      if (!isControlled) return;
      if (parseText(textRef.current) === value) return;
      const next = value === null ? '' : formatValue(value, precision);
      textRef.current = next;
      setText(next);
    }, [isControlled, value, precision]);

    // Last shown error type reported to `onErrorChange`, so it fires on change only.
    const reportedRef = React.useRef<string | null>(null);
    const showError = (show: boolean, nextError: InputNumberError | null) => {
      setErrorShown(show);
      const shown = show ? nextError : null;
      const key = shown ? shown.type : null;
      if (key === reportedRef.current) return;
      reportedRef.current = key;
      onErrorChange?.(shown);
    };

    const setRefs = React.useCallback(
      (node: HTMLInputElement | null) => {
        fieldRef.current = node;
        assignRef(ref, node);
      },
      [ref],
    );

    const commit = (next: string) => {
      const prevValue = parseText(textRef.current);
      textRef.current = next;
      setText(next);
      const nextError = validate(next, rules);
      // Early clear: fixed while typing (or stepping) = the red goes now.
      if (!nextError && errorShown) showError(false, null);
      const nextValue = parseText(next);
      if (nextValue !== prevValue) onChange?.(nextValue, { error: nextError });
    };

    const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
      const next = sanitizeInput(event.target.value, allowNegative);
      // Rejected keystroke: the text state is unchanged, so React restores the box.
      if (next === null) return;
      commit(next);
    };

    const handleBlur = (event: React.FocusEvent<HTMLInputElement>) => {
      const nextError = validate(textRef.current, rules);
      showError(nextError !== null, nextError);
      // Pad a valid value to precision ("1." → "1", 1 → "1.00"); an over-precise
      // one is left exactly as typed (§4.2).
      const parsed = parseText(textRef.current);
      if (parsed === null) {
        if (textRef.current !== '') commit('');
      } else if (!nextError || nextError.type === 'range') {
        const formatted = formatValue(parsed, precision);
        if (formatted !== textRef.current) {
          textRef.current = formatted;
          setText(formatted);
        }
      }
      onBlur?.(event);
    };

    const atMax = (v: number | null) => v !== null && max !== undefined && v >= max;
    const atMin = (v: number | null) => v !== null && min !== undefined && v <= min;

    /** One step; returns false when it hit a bound, so a held button stops. */
    const stepBy = (direction: 1 | -1, multiplier = 1): boolean => {
      const now = parseText(textRef.current);
      if (direction > 0 ? atMax(now) : atMin(now)) return false;
      const next = stepValue(now, direction * step * multiplier, bounds);
      commit(formatValue(next, Math.max(precision, countDecimals(next))));
      return direction > 0 ? !atMax(next) : !atMin(next);
    };

    // ---- press-and-hold (落地 5) ----
    const timers = React.useRef<{ delay?: number; repeat?: number }>({});
    const stopRepeat = React.useCallback(() => {
      window.clearTimeout(timers.current.delay);
      window.clearInterval(timers.current.repeat);
      timers.current = {};
    }, []);
    React.useEffect(() => stopRepeat, [stopRepeat]);

    const handleStepPointerDown = (direction: 1 | -1) => (event: React.PointerEvent) => {
      if (event.button !== 0) return;
      // Keep the caret in the box; the box gets focus so ↑ / ↓ work next.
      event.preventDefault();
      fieldRef.current?.focus();
      stopRepeat();
      if (!stepBy(direction)) return;
      // A button that turns disabled under the pointer never gets its pointerup,
      // so the release is listened for on the window.
      window.addEventListener('pointerup', stopRepeat, { once: true });
      window.addEventListener('pointercancel', stopRepeat, { once: true });
      timers.current.delay = window.setTimeout(() => {
        timers.current.repeat = window.setInterval(() => {
          if (!stepBy(direction)) stopRepeat();
        }, REPEAT_INTERVAL);
      }, REPEAT_DELAY);
    };

    // Assistive tech "clicks" without a pointer (detail === 0).
    const handleStepClick = (direction: 1 | -1) => (event: React.MouseEvent) => {
      if (event.detail === 0) stepBy(direction);
    };

    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
      onKeyDown?.(event);
      if (event.defaultPrevented || !editable) return;
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
      event.preventDefault();
      stepBy(event.key === 'ArrowUp' ? 1 : -1, event.shiftKey ? 10 : 1);
    };

    const effectiveStatus: InputStatus = shownError ? 'error' : status;
    const message = shownError && errorMessage ? errorMessage(shownError) : null;

    return (
      <div className={cn('flex w-full flex-col gap-1', className)}>
        <div
          className={shellStyles({ size, status: effectiveStatus, state, borderless })}
          onPointerDown={(event) => {
            if (!disabled) focusFieldFromShell(event, fieldRef.current);
          }}
        >
          <div className={CONTROL_ROW[size]}>
            {prefix !== undefined && (
              <span className="flex shrink-0 items-center text-text-3">{prefix}</span>
            )}
            <input
              ref={setRefs}
              // Not type="number" (落地 2): native spinners, wheel stepping and
              // the "e" notation are exactly what §2.1 / §4.2 rule out.
              type="text"
              inputMode={precision > 0 ? 'decimal' : 'numeric'}
              role="spinbutton"
              autoComplete="off"
              aria-valuemin={min}
              aria-valuemax={max}
              aria-valuenow={current ?? undefined}
              aria-invalid={shownError !== null || status === 'error' || undefined}
              className={cn(FIELD_BASE, inputClassName)}
              disabled={disabled}
              readOnly={readOnly}
              value={text}
              onChange={handleChange}
              onBlur={handleBlur}
              onKeyDown={handleKeyDown}
              {...props}
            />
          </div>
          {/* §2.1 — the column's 20px is always reserved; only its content
              appears on hover. Read-only / disabled render it empty (§5.1),
              touch drops it entirely (§6: no hover, half-height targets).
              With a unit the column sits LEFT of it (§2), so the unit closes
              the box instead of floating before a blank strip. */}
          <div
            className={cn(
              'flex w-5 shrink-0 flex-col [@media(hover:none)_and_(pointer:coarse)]:hidden',
              editable &&
                'border-l border-border-base opacity-0 transition-opacity group-hover:opacity-100',
              editable && suffix !== undefined && 'border-r',
            )}
            aria-hidden={editable ? undefined : true}
          >
            {editable && (
              <>
                <button
                  type="button"
                  tabIndex={-1}
                  aria-label={increaseLabel}
                  className={STEP_BUTTON}
                  disabled={atMax(current)}
                  onPointerDown={handleStepPointerDown(1)}
                  onClick={handleStepClick(1)}
                >
                  {/* 12px in every size档, pinned inline like the clear icon. */}
                  <Outlined.Up style={{ width: 12, height: 12 }} />
                </button>
                <button
                  type="button"
                  tabIndex={-1}
                  aria-label={decreaseLabel}
                  className={cn(STEP_BUTTON, 'border-t border-border-base')}
                  disabled={atMin(current)}
                  onPointerDown={handleStepPointerDown(-1)}
                  onClick={handleStepClick(-1)}
                >
                  <Outlined.Down style={{ width: 12, height: 12 }} />
                </button>
              </>
            )}
          </div>
          {suffix !== undefined && (
            <span className={cn('flex shrink-0 items-center text-text-3', SUFFIX_PADDING[size])}>
              {suffix}
            </span>
          )}
        </div>
        {message !== null && (
          <span className="text-[length:var(--font-size-1)] leading-[var(--line-height-1)] text-danger">
            {message}
          </span>
        )}
      </div>
    );
  },
);
