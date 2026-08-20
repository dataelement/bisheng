import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import {
  ADDON_BASE,
  ADDON_PADDING,
  CLEAR_VISIBILITY,
  CONTROL_ROW,
  COUNT_BASE,
  FIELD_ACTION,
  FIELD_BASE,
  assignRef,
  clearField,
  focusFieldFromShell,
  resolveState,
  shellStyles,
  useFieldText,
  type InputSize,
  type InputStatus,
} from './shared';

/**
 * Input — the single-line text field (组件-Input输入框.md v1).
 *
 * One base for every single-line form (§2): the plain field, and — by filling
 * the prefix / suffix / addon slots — search, password and unit-prefixed
 * fields. Password / Search ship as thin wrappers over this same component
 * rather than as an API of their own.
 *
 * What the component pins down and a page cannot restate: the 24/32/40 height
 * ladder with its radii and paddings (§3), the gray focus chain (§5.1 — no
 * brand color on focus, ever), the four state shells (§5.2), and the touch
 * rules (§6: no hover, 16px type to stop iOS zooming, ≥44px hot zone).
 *
 * Not this component: a value picked from a fixed list (that is a select), or
 * anything that needs more than one line (that is `Textarea`).
 */
export interface InputProps
  // `size` is our ladder, not the HTML character-count attr; `prefix` is our
  // slot, not the RDFa attribute of the same name.
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size' | 'prefix'> {
  /** §3 — pick the档, never hand-write height / padding. */
  size?: InputSize;
  /** §5.2 — `error` blocks submit and turns the border red; `warning` is "look again". */
  status?: InputStatus;
  /** §4.2 — says WHAT the box is (magnifier, link icon). */
  prefix?: React.ReactNode;
  /** §4.2 — a unit, a counter, or an action; at most two action icons. */
  suffix?: React.ReactNode;
  /** §2 — a fixed part of the value (`https://`, `元`), fused into the outline. */
  addonBefore?: React.ReactNode;
  addonAfter?: React.ReactNode;
  /** §4.3 — on for search / filter fields, off for form fields where a mis-tap costs real typing. */
  allowClear?: boolean;
  /** Accessible name of the clear button — text comes from the caller (library contract). */
  clearLabel?: string;
  /** Fires after the box is emptied; the `onChange` for the empty value fires too. */
  onClear?: () => void;
  /** §4.4 — "current / limit"; needs `maxLength`, and only for limits users actually hit. */
  showCount?: boolean;
  /** Classes for the shell (width lives here: `className="w-64"`). */
  className?: string;
  /** Classes for the `<input>` itself — rarely needed. */
  inputClassName?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    size = 'medium',
    status = 'default',
    prefix,
    suffix,
    addonBefore,
    addonAfter,
    allowClear = false,
    clearLabel,
    onClear,
    showCount = false,
    className,
    inputClassName,
    disabled,
    readOnly,
    value,
    defaultValue,
    onChange,
    maxLength,
    ...props
  },
  ref,
) {
  const fieldRef = React.useRef<HTMLInputElement | null>(null);
  const { text, track } = useFieldText(value, defaultValue);
  const state = resolveState(disabled, readOnly);

  const setRefs = React.useCallback(
    (node: HTMLInputElement | null) => {
      fieldRef.current = node;
      assignRef(ref, node);
    },
    [ref],
  );

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    track(event.target.value);
    onChange?.(event);
  };

  const handleClear = () => {
    clearField(fieldRef.current);
    onClear?.();
  };

  // §4.3 — a clear button on a field nobody can edit would be a lie.
  const showClear = allowClear && !disabled && !readOnly && text.length > 0;
  // §4.4 — the counter only makes sense against a limit.
  const countVisible = showCount && maxLength !== undefined;
  const atLimit = maxLength !== undefined && text.length >= maxLength;

  return (
    <div
      className={cn(shellStyles({ size, status, state }), className)}
      onPointerDown={(event) => {
        if (!disabled) focusFieldFromShell(event, fieldRef.current);
      }}
    >
      {addonBefore !== undefined && (
        <span
          data-input-addon="before"
          className={cn(ADDON_BASE, ADDON_PADDING[size], 'border-r border-border-base')}
        >
          {addonBefore}
        </span>
      )}
      <div className={CONTROL_ROW[size]}>
        {prefix !== undefined && (
          <span className="flex shrink-0 items-center text-text-3">{prefix}</span>
        )}
        <input
          ref={setRefs}
          className={cn(FIELD_BASE, inputClassName)}
          disabled={disabled}
          readOnly={readOnly}
          value={value}
          defaultValue={defaultValue}
          onChange={handleChange}
          maxLength={maxLength}
          aria-invalid={status === 'error' || undefined}
          {...props}
        />
        {countVisible && (
          <span className={cn(COUNT_BASE, atLimit ? 'text-danger' : 'text-text-3')}>
            {text.length} / {maxLength}
          </span>
        )}
        {showClear && (
          <button
            type="button"
            tabIndex={-1}
            aria-label={clearLabel}
            className={cn(FIELD_ACTION, CLEAR_VISIBILITY)}
            // Keep the caret (and the focus ring) in the box while clearing.
            onMouseDown={(event) => event.preventDefault()}
            onClick={handleClear}
          >
            <Outlined.CloseCircle />
          </button>
        )}
        {suffix !== undefined && (
          <span className="flex shrink-0 items-center text-text-3">{suffix}</span>
        )}
      </div>
      {addonAfter !== undefined && (
        <span
          data-input-addon="after"
          className={cn(ADDON_BASE, ADDON_PADDING[size], 'border-l border-border-base')}
        >
          {addonAfter}
        </span>
      )}
    </div>
  );
});
