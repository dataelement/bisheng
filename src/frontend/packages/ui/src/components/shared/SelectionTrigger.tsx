import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { Filled, Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { buttonVariants } from '../Button/Button';
import { FIELD_ACTION, resolveState, shellStyles, type InputSize, type InputStatus } from '../Input/shared';
import { RADIUS_CLASS, type RadiusToken } from './menuSurface';

export type SelectionVariant = 'outlined' | 'ghost' | 'icon';

/** The Select/Cascader icon ladder: 14 / 16 / 18. */
export const SELECTION_CHEVRON_SIZE: Record<InputSize, number> = {
  small: 14,
  medium: 16,
  large: 18,
};

const OUTLINED_ROW: Record<InputSize, string> = {
  small: 'gap-1 px-[7px]',
  medium: 'gap-2 px-[11px]',
  large: 'gap-2 px-[11px]',
};

const TAG_ROW_START: Record<InputSize, string> = {
  small: 'pl-px',
  medium: 'pl-[5px]',
  large: 'pl-[9px]',
};

const GHOST_PADDING: Record<InputSize, string> = {
  small: 'gap-1 px-1',
  medium: 'gap-1 px-2',
  large: 'gap-1 px-2',
};

export interface SelectionTriggerProps {
  size: InputSize;
  status: InputStatus;
  variant: SelectionVariant;
  radius?: RadiusToken;
  disabled: boolean;
  readOnly: boolean;
  open: boolean;
  interactive: boolean;
  hasValue: boolean;
  allowClear: boolean;
  clearLabel: string;
  body: React.ReactNode;
  /** Adds the Select tag inset without teaching the shared shell about values. */
  hasMultipleTags?: boolean;
  customTrigger?: React.ReactElement;
  className?: string;
  comboboxProps: React.HTMLAttributes<HTMLElement>;
  onTriggerClick: (event: React.MouseEvent<HTMLElement>) => void;
  onClear: () => void;
}

/**
 * The visual and interactive shell shared by Select and Cascader. The caller
 * owns values and search; this owns the family resemblance: Input shell,
 * padding, arrow/clear swap, open state, ghost/icon variants and icon tooltip.
 */
export const SelectionTrigger = React.forwardRef<HTMLElement, SelectionTriggerProps>(
  function SelectionTrigger(
    {
      size,
      status,
      variant,
      radius,
      disabled,
      readOnly,
      open,
      interactive,
      hasValue,
      allowClear,
      clearLabel,
      body,
      hasMultipleTags = false,
      customTrigger,
      className,
      comboboxProps,
      onTriggerClick,
      onClear,
    },
    ref,
  ) {
    const outlined = variant === 'outlined';
    const iconSize = SELECTION_CHEVRON_SIZE[size];
    const showClear = allowClear && interactive && hasValue;

    const suffix = !readOnly && (
      <span className="relative flex shrink-0 items-center text-text-3">
        <Outlined.Down
          aria-hidden
          style={{ width: iconSize, height: iconSize }}
          className={cn('transition-transform', open && 'rotate-180', showClear && 'group-hover:invisible')}
        />
        {showClear && (
          <button
            type="button"
            tabIndex={-1}
            aria-label={clearLabel}
            className={cn(
              FIELD_ACTION,
              'invisible absolute inset-0 text-text-4 hover:text-text-3 group-hover:visible',
            )}
            onMouseDown={(event) => event.preventDefault()}
            onClick={(event) => {
              event.stopPropagation();
              onClear();
            }}
          >
            <Filled.CloseCircle style={{ width: 14, height: 14 }} />
          </button>
        )}
      </span>
    );

    let node: React.ReactElement;
    if (customTrigger !== undefined) {
      node = (
        <Slot
          ref={ref}
          {...comboboxProps}
          data-menu-open={open ? '' : undefined}
          onClick={onTriggerClick}
        >
          {customTrigger}
        </Slot>
      );
    } else if (outlined) {
      node = (
        <div
          ref={ref as React.ForwardedRef<HTMLDivElement>}
          {...comboboxProps}
          data-state={open ? 'open' : 'closed'}
          onClick={onTriggerClick}
          className={cn(
            shellStyles({ size, status, state: resolveState(disabled, readOnly) }),
            'outline-none',
            interactive && 'cursor-pointer',
            open && 'shadow-focus',
            open && status === 'default' && 'border-border-deep',
            radius && RADIUS_CLASS[radius],
            className,
          )}
        >
          <div
            className={cn(
              'flex min-w-0 flex-1 items-center',
              OUTLINED_ROW[size],
              hasMultipleTags && TAG_ROW_START[size],
            )}
          >
            {body}
            {suffix}
          </div>
        </div>
      );
    } else {
      node = (
        <div
          ref={ref as React.ForwardedRef<HTMLDivElement>}
          {...comboboxProps}
          data-state={open ? 'open' : 'closed'}
          data-menu-open={open ? '' : undefined}
          onClick={onTriggerClick}
          className={cn(
            buttonVariants({ color: 'default', variant: 'text', size }),
            'group max-w-full justify-start',
            GHOST_PADDING[size],
            interactive ? 'cursor-pointer' : 'cursor-default',
            disabled && 'cursor-not-allowed text-btn-disabled-text hover:bg-transparent',
            radius && RADIUS_CLASS[radius],
            className,
          )}
        >
          {body}
          {suffix}
        </div>
      );
    }

    return node;
  },
);
