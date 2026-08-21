import * as React from 'react';
import { cva } from 'class-variance-authority';

/**
 * Shared internals of the input family (组件-Input输入框.md v1).
 *
 * Input / Textarea / Password / Search are ONE base with different slots filled
 * (§2), so the shell — border, radius, height ladder, the four state colors and
 * the focus ring — is defined once here and every form imports it.
 */

/** §3 — three sizes, same 24/32/40 ladder as the button, so a row lines up. */
export type InputSize = 'small' | 'medium' | 'large';

/** §5.2 — validation status. `error` blocks submit, `warning` does not. */
export type InputStatus = 'default' | 'error' | 'warning';

/** Which of the three shells the field is in — derived from `disabled` / `readOnly`. */
type InputState = 'editable' | 'readonly' | 'disabled';

/**
 * §5 — the shell draws EVERYTHING the eye reads as "the input": border, fill,
 * radius, height and the focus ring. The `<input>` inside is transparent and
 * borderless, which is what lets prefix / suffix / addon share one outline.
 *
 * The state chain is one gray ramp (§5.1): base border → deep on hover → deep +
 * a 2px gray ring on focus. No brand color anywhere — focus only answers "where
 * is the caret", and the color budget is saved for validation.
 */
export const shellStyles = cva(
  'group relative flex w-full items-stretch overflow-hidden border transition-colors',
  {
    variants: {
      // Height + radius + type size per §3. Font size references the PRIMITIVE
      // scale vars on purpose: the semantic --text-body remaps 14→16 under
      // 768px for READING text, while a control's own mobile rule is the iOS
      // anti-zoom one, which `.input-no-zoom` applies to the field only (§6).
      size: {
        small:
          'input-touch-hit h-6 rounded text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
        medium:
          'input-touch-hit h-8 rounded-md text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
        large:
          'input-touch-hit h-10 rounded-lg text-[length:var(--font-size-4)] leading-[var(--line-height-4)]',
      },
      // Validation border. The ring color rides along as a CSS var so the focus
      // ring switches to the matching tint without a second shadow token (§5.2).
      status: {
        default: '',
        error: 'border-danger [--shadow-focus-ring:var(--danger-tint)]',
        warning: 'border-warning [--shadow-focus-ring:var(--warning-tint)]',
      },
      state: {
        editable: 'bg-bg-page text-text-1',
        // §5.2 — readonly is "valid content you may copy but not change":
        // light fill, normal border, and NO focus ring (nothing to type into).
        readonly: 'bg-fill-1 text-text-1',
        // §5.2 — disabled reuses the button's three tokens verbatim.
        disabled:
          'cursor-not-allowed border-btn-disabled-border bg-btn-disabled-bg text-btn-disabled-text',
      },
    },
    compoundVariants: [
      // Only an editable field reacts to the pointer. `hover:` is compiled
      // inside a hover-capable media query app-wide, so touch goes straight
      // from default to focus (§6) without any variant of our own.
      {
        state: 'editable',
        status: 'default',
        class:
          'border-border-base hover:border-border-deep focus-within:border-border-deep focus-within:shadow-focus',
      },
      // A field that is saying something keeps saying it while hovered and
      // focused — the gray ramp must not overwrite the validation color.
      {
        state: 'editable',
        status: 'error',
        class: 'hover:border-danger focus-within:border-danger focus-within:shadow-focus',
      },
      {
        state: 'editable',
        status: 'warning',
        class: 'hover:border-warning focus-within:border-warning focus-within:shadow-focus',
      },
      { state: 'readonly', status: 'default', class: 'border-border-base' },
    ],
    defaultVariants: { size: 'medium', status: 'default', state: 'editable' },
  },
);

/** §3/§4.2 — inner row: 8/12/12 horizontal padding minus the 1px border, and the 14/16/18 icon ladder. */
export const CONTROL_ROW: Record<InputSize, string> = {
  small: 'flex min-w-0 flex-1 items-center gap-1 px-[7px] [&_svg]:size-3.5',
  medium: 'flex min-w-0 flex-1 items-center gap-2 px-[11px] [&_svg]:size-4',
  large: 'flex min-w-0 flex-1 items-center gap-2 px-[11px] [&_svg]:size-[18px]',
};

/** §2 — addon shares the shell's outline; only a divider separates it from the field. */
export const ADDON_PADDING: Record<InputSize, string> = {
  small: 'px-2',
  medium: 'px-3',
  large: 'px-3',
};

export const ADDON_BASE =
  'flex shrink-0 items-center whitespace-nowrap bg-fill-1 text-text-2';

/**
 * The field itself: no chrome of its own (the shell owns it), inheriting the
 * shell's type size. `.input-no-zoom` is the iOS anti-zoom rule (§6);
 * `::-ms-*` are Edge's built-in reveal / clear buttons, which would double up
 * with ours.
 */
export const FIELD_BASE =
  'input-no-zoom min-w-0 flex-1 border-0 bg-transparent p-0 text-inherit outline-none placeholder:text-text-3 disabled:cursor-not-allowed disabled:text-btn-disabled-text disabled:placeholder:text-btn-disabled-text [&::-ms-clear]:hidden [&::-ms-reveal]:hidden';

/**
 * §4.2/§4.3 — a suffix ACTION (clear, reveal). `btn-touch-hit` gives it the
 * ≥44px hot zone on touch while the icon stays 14/16/18.
 */
export const FIELD_ACTION =
  'btn-touch-hit relative flex shrink-0 cursor-pointer items-center justify-center text-text-3 outline-none transition-colors hover:text-text-2';

/**
 * §4.3 — the clear button shows on hover or focus, and only with content in the
 * box. `invisible` (not conditional rendering) keeps the row from jittering.
 * Touch has no hover, so `group-hover:` compiles out there and focus alone
 * shows it — exactly what the mobile table asks for.
 */
export const CLEAR_VISIBILITY = 'invisible group-hover:visible group-focus-within:visible';

/** §4.4 — counter: hint color normally, danger once the limit is reached. */
export const COUNT_BASE =
  'shrink-0 select-none tabular-nums text-[length:var(--font-size-1)] leading-[var(--line-height-1)]';

function toText(value: string | number | readonly string[] | undefined): string {
  if (value === undefined || value === null) return '';
  return Array.isArray(value) ? value.join('') : String(value);
}

/**
 * Clear (§4.3) and count (§4.4) both need to know what is in the box, which
 * controlled callers keep in their own state and uncontrolled ones do not keep
 * at all. This mirrors the value so both call sites read one variable.
 */
export function useFieldText(
  value: string | number | readonly string[] | undefined,
  defaultValue: string | number | readonly string[] | undefined,
): { text: string; track: (next: string) => void } {
  const [innerText, setInnerText] = React.useState(() => toText(defaultValue));
  const isControlled = value !== undefined;
  const track = React.useCallback(
    (next: string) => {
      if (!isControlled) setInnerText(next);
    },
    [isControlled],
  );
  return { text: isControlled ? toText(value) : innerText, track };
}

/**
 * Empty the field the way the user would: go through the NATIVE value setter and
 * dispatch `input`, so React's own `onChange` fires and a controlled caller
 * updates its state — assigning `node.value` alone is swallowed by React's value
 * tracker. Focus stays in the box so the user can retype straight away (§4.3).
 */
export function clearField(node: HTMLInputElement | HTMLTextAreaElement | null): void {
  if (!node) return;
  const proto =
    node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setValue = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
  setValue?.call(node, '');
  node.dispatchEvent(new Event('input', { bubbles: true }));
  node.focus();
}

/** Keeps the caller's ref working while the component holds one of its own. */
export function assignRef<T>(ref: React.ForwardedRef<T>, node: T | null): void {
  if (typeof ref === 'function') ref(node);
  else if (ref) ref.current = node;
}

/** `disabled` / `readOnly` decide the shell; both together read as disabled. */
export function resolveState(disabled?: boolean, readOnly?: boolean): InputState {
  if (disabled) return 'disabled';
  if (readOnly) return 'readonly';
  return 'editable';
}

/**
 * A tap on the padding — or on the invisible hot zone above/below the field
 * (§6) — should land in the box. Anything that handles its own click (the
 * field, the clear button, an addon the user may want to select) is skipped.
 */
export function focusFieldFromShell(
  event: React.PointerEvent<HTMLElement>,
  node: HTMLInputElement | HTMLTextAreaElement | null,
): void {
  const target = event.target as HTMLElement | null;
  if (!node || !target) return;
  if (target.closest('input, textarea, button, a, [data-input-addon]')) return;
  event.preventDefault();
  node.focus();
}
