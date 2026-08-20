import * as React from 'react';
import cn from '../../utils/cn';
import { FIELD_ACTION } from './shared';
import { Input, type InputProps } from './Input';

/**
 * PasswordInput — the password form of the base field (组件-Input输入框.md §2).
 *
 * Masked by default with a reveal toggle in the suffix, because that action
 * belongs to the box: a "show password" button parked outside it breaks the
 * form's alignment (§4.2). Combined with `allowClear` the suffix carries the
 * two actions the spec allows, and no more.
 *
 * The two icons come in as props: the icon package has no eye glyph yet, and
 * the library contract forbids drawing one here. Pass the app's own pair
 * (see the docs page) until `bisheng-icons` ships one.
 */
export interface PasswordInputProps extends Omit<InputProps, 'type' | 'suffix'> {
  /** Shown while the value is masked — clicking it reveals the text. */
  revealIcon: React.ReactNode;
  /** Shown while the value is visible — clicking it masks the text again. */
  hideIcon: React.ReactNode;
  /** Accessible name of the toggle while masked (caller-supplied copy). */
  revealLabel?: string;
  /** Accessible name of the toggle while revealed. */
  hideLabel?: string;
  /** Start revealed — for a generated key the user is meant to read. */
  defaultVisible?: boolean;
  onVisibleChange?: (visible: boolean) => void;
}

export const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  function PasswordInput(
    {
      revealIcon,
      hideIcon,
      revealLabel,
      hideLabel,
      defaultVisible = false,
      onVisibleChange,
      disabled,
      ...props
    },
    ref,
  ) {
    const [visible, setVisible] = React.useState(defaultVisible);

    const toggle = () => {
      const next = !visible;
      setVisible(next);
      onVisibleChange?.(next);
    };

    return (
      <Input
        ref={ref}
        type={visible ? 'text' : 'password'}
        disabled={disabled}
        suffix={
          <button
            type="button"
            aria-label={visible ? hideLabel : revealLabel}
            aria-pressed={visible}
            disabled={disabled}
            className={cn(FIELD_ACTION, disabled && 'cursor-not-allowed')}
            // Toggling must not steal the caret out of the field.
            onMouseDown={(event) => event.preventDefault()}
            onClick={toggle}
          >
            {visible ? hideIcon : revealIcon}
          </button>
        }
        {...props}
      />
    );
  },
);
