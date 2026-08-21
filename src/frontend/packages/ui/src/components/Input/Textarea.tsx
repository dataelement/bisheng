import * as React from 'react';
import cn from '../../utils/cn';
import {
  COUNT_BASE,
  assignRef,
  focusFieldFromShell,
  resolveState,
  shellStyles,
  useFieldText,
  type InputStatus,
} from './shared';

/**
 * Textarea — the multi-line form of the field (组件-Input输入框.md §2/§3).
 *
 * Same shell as `Input` (one border, one focus ring, same four states) with the
 * height ladder switched off: a textarea has no size档 — 14/22 type, 6px radius,
 * 8/12 padding, three rows tall by default.
 *
 * Vertical resize is left to the user, horizontal is not: a box that grows past
 * its column breaks the form's grid. Auto-grow is deliberately not built in —
 * §3 requires a ceiling for it, and no caller has needed one yet.
 */
export interface TextareaProps
  extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, 'cols'> {
  /** §5.2 — same validation states as the single-line field. */
  status?: InputStatus;
  /** §4.4 — "current / limit", parked in the bottom-right corner INSIDE the box. */
  showCount?: boolean;
  /** Classes for the shell (width / min-height live here). */
  className?: string;
  /** Classes for the `<textarea>` itself. */
  textareaClassName?: string;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    status = 'default',
    showCount = false,
    className,
    textareaClassName,
    disabled,
    readOnly,
    value,
    defaultValue,
    onChange,
    maxLength,
    rows = 3,
    ...props
  },
  ref,
) {
  const fieldRef = React.useRef<HTMLTextAreaElement | null>(null);
  const { text, track } = useFieldText(value, defaultValue);
  const state = resolveState(disabled, readOnly);

  const setRefs = React.useCallback(
    (node: HTMLTextAreaElement | null) => {
      fieldRef.current = node;
      assignRef(ref, node);
    },
    [ref],
  );

  const handleChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    track(event.target.value);
    onChange?.(event);
  };

  const countVisible = showCount && maxLength !== undefined;
  const atLimit = maxLength !== undefined && text.length >= maxLength;

  return (
    <div
      // `h-auto` drops the single-line height: the row count decides how tall
      // this is, and the user may drag it taller.
      className={cn(shellStyles({ size: 'medium', status, state }), 'h-auto', className)}
      onPointerDown={(event) => {
        if (!disabled) focusFieldFromShell(event, fieldRef.current);
      }}
    >
      <textarea
        ref={setRefs}
        rows={rows}
        className={cn(
          'input-no-zoom w-full resize-y border-0 bg-transparent px-3 py-2 text-inherit outline-none placeholder:text-text-3 disabled:cursor-not-allowed disabled:text-btn-disabled-text disabled:placeholder:text-btn-disabled-text',
          // Room for the counter so the last line never runs under it.
          countVisible && 'pb-7',
          textareaClassName,
        )}
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
        // `bg-inherit` so scrolled text passes UNDER the counter, not through it.
        <span
          className={cn(
            COUNT_BASE,
            'pointer-events-none absolute bottom-1.5 right-3 rounded bg-inherit px-1',
            atLimit ? 'text-danger' : 'text-text-3',
          )}
        >
          {text.length} / {maxLength}
        </span>
      )}
    </div>
  );
});
