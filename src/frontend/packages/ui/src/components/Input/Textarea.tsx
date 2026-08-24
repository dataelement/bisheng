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
  /**
   * §4.4 — "current / limit", parked in the bottom-right corner INSIDE the box.
   * The limit is SOFT, same as the single-line field: typing past it is allowed
   * and the counter turns red; rejecting the value is the form's job.
   */
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
  // Over, not at: "50 / 50" is still a valid value, "51 / 50" is not.
  const overLimit = maxLength !== undefined && text.length > maxLength;

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
          // The floor for the user's own drag is the 32px medium-control height
          // (§3), and at that floor one line has to sit CENTERED and whole:
          // 1px border + 4 + 22 (line) + 4 + 1px border = 32. That is what fixes
          // the vertical padding at 4px — 8px would need a 40px box, and a
          // dragged-flat field would show a line cut off at both ends.
          'input-no-zoom min-h-[30px] w-full resize-y border-0 bg-transparent px-3 py-1 text-inherit outline-none placeholder:text-text-3 disabled:cursor-not-allowed disabled:text-btn-disabled-text disabled:placeholder:text-btn-disabled-text',
          // Room for the counter so the last line never runs under it — and the
          // floor grows by the same amount (4 + 22 + 28), or dragging flat would
          // bury the line behind the counter.
          countVisible && 'min-h-[54px] pb-7',
          textareaClassName,
        )}
        disabled={disabled}
        readOnly={readOnly}
        value={value}
        defaultValue={defaultValue}
        onChange={handleChange}
        // Not forwarded to the DOM on purpose — see Input.tsx / §4.4.
        aria-invalid={status === 'error' || overLimit || undefined}
        {...props}
      />
      {countVisible && (
        // `bg-inherit` so scrolled text passes UNDER the counter, not through it.
        <span
          className={cn(
            COUNT_BASE,
            'pointer-events-none absolute bottom-1.5 right-3 rounded bg-inherit px-1',
            overLimit ? 'text-danger' : 'text-text-3',
          )}
        >
          {text.length} / {maxLength}
        </span>
      )}
    </div>
  );
});
