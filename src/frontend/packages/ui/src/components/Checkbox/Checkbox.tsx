import * as React from 'react';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import {
  CARD_DESCRIPTION,
  CARD_LABEL,
  CARD_SHELL,
  CONTROL_BASE,
  CONTROL_CHECKED,
  CONTROL_OFFSET,
  CONTROL_SIZE,
  DESCRIPTION,
  GROUP_LAYOUT,
  ROW_BASE,
  ROW_HOVER_CONTROL,
  ROW_TEXT,
  type SelectionSize,
} from '../Selection/shared';

/**
 * Checkbox — design-system base component (组件-Checkbox复选框.md v1).
 *
 * Picks SEVERAL from a set (or a single "I agree" tick); the result travels
 * with the form — a setting that applies the moment it is flipped is a Switch.
 * Baked in per spec: the 14/16/18 ladder with its fixed 4px radius (§3), the
 * gray→brand state chain with indeterminate reserved for select-all (§5), the
 * button's three disabled tokens + gray label (§5's three signals), the
 * keyboard-only gray focus ring, and the ≥44px touch row (§6). Radix keeps the
 * a11y contract (`aria-checked="mixed"` for indeterminate).
 */

/** §5 — indeterminate paints exactly like checked; only the mark differs. */
const CONTROL_INDETERMINATE =
  'data-[state=indeterminate]:border-blue-500 data-[state=indeterminate]:bg-blue-500 data-[state=indeterminate]:text-white';

/** §5 — the indeterminate bar, scaled 6/8/10 with the box. */
const BAR_WIDTH: Record<SelectionSize, string> = {
  small: 'w-1.5',
  medium: 'w-2',
  large: 'w-2.5',
};

export interface CheckboxProps
  extends Omit<React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>, 'asChild'> {
  /** §3 — control ladder; medium is the default. */
  size?: SelectionSize;
  /** Option text — part of the hot zone (§4: 点字即点框). */
  label?: React.ReactNode;
  /** One secondary line under the label, hint color (§4). */
  description?: React.ReactNode;
  /** Class for the wrapping <label> when `label`/`description` is present. */
  wrapperClassName?: string;
}

/** The box itself — shared by the basic row and the card form. */
function renderControl(
  size: SelectionSize,
  className: string | undefined,
  inRow: boolean,
  props: Omit<CheckboxProps, 'size' | 'label' | 'description' | 'wrapperClassName' | 'className'>,
  ref: React.ForwardedRef<HTMLButtonElement>,
) {
  return (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn(
        'group/box rounded',
        CONTROL_BASE,
        CONTROL_CHECKED,
        CONTROL_INDETERMINATE,
        CONTROL_SIZE[size],
        inRow && CONTROL_OFFSET[size],
        inRow && ROW_HOVER_CONTROL,
        className,
      )}
      {...props}
    >
      {/* forceMount + scale keep the mark in the DOM so it can animate in AND
          out (200ms, same clock as the Switch thumb / Radio dot) — radix would
          otherwise unmount it and the check pops. */}
      <CheckboxPrimitive.Indicator
        forceMount
        className="flex scale-0 items-center justify-center text-current transition-transform duration-200 data-[state=checked]:scale-100 data-[state=indeterminate]:scale-100"
      >
        {/* strokeWidth 3 on the 24-viewBox icon = 1.5px at the medium box's
            12px display size (designer-tuned 2026-08-25: 2px read too heavy,
            the default 2 → 1px hairline too thin). The indeterminate bar below
            is 1.5px to match. */}
        <Outlined.Check strokeWidth={3} className="group-data-[state=indeterminate]/box:hidden" />
        {/* Not an icon — the §5 indeterminate bar, drawn in currentColor so the
            disabled override grays it along with the check. */}
        <span
          className={cn(
            'hidden h-[1.5px] rounded-full bg-current group-data-[state=indeterminate]/box:block',
            BAR_WIDTH[size],
          )}
        />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ size = 'medium', label, description, wrapperClassName, className, ...props }, ref) => {
    const hasRow = label !== undefined || description !== undefined;
    const control = renderControl(size, className, hasRow, props, ref);
    if (!hasRow) return control;
    return (
      <label className={cn(ROW_BASE, ROW_TEXT[size], wrapperClassName)}>
        {control}
        <span className="flex min-w-0 flex-col">
          {label !== undefined && <span>{label}</span>}
          {description !== undefined && <span className={DESCRIPTION}>{description}</span>}
        </span>
      </label>
    );
  },
);
Checkbox.displayName = 'Checkbox';

export interface CheckboxGroupProps extends React.HTMLAttributes<HTMLDivElement> {
  /** §2 — horizontal 16px gaps / vertical 8px; narrow screens always stack. */
  direction?: 'horizontal' | 'vertical';
}

/**
 * Layout shell for a set of parallel options (§2). State stays on the
 * individual checkboxes — a group is spacing plus a `group` role, nothing more
 * (validation copy is rendered by the caller, same as the Input family).
 */
function CheckboxGroup({ direction = 'horizontal', className, ...props }: CheckboxGroupProps) {
  return <div role="group" className={cn(GROUP_LAYOUT[direction], className)} {...props} />;
}

export interface CheckboxCardProps extends Omit<CheckboxProps, 'wrapperClassName'> {
  /** Card title — medium weight, body color (§2). */
  label: React.ReactNode;
  /** Class for the card shell (the <label>). */
  wrapperClassName?: string;
}

/**
 * Card form (§2) — the basic box in a card shell: whole card clickable,
 * selection tints the card while the border stays gray, radius 12 / min-height
 * 48. Options with a title + description (plan / package pickers).
 */
const CheckboxCard = React.forwardRef<HTMLButtonElement, CheckboxCardProps>(
  ({ size = 'medium', label, description, wrapperClassName, className, ...props }, ref) => (
    <label className={cn(CARD_SHELL, wrapperClassName)}>
      {renderControl(size, className, false, props, ref)}
      <span className={CARD_LABEL}>{label}</span>
      {description !== undefined && <span className={CARD_DESCRIPTION}>{description}</span>}
    </label>
  ),
);
CheckboxCard.displayName = 'CheckboxCard';

export { Checkbox, CheckboxGroup, CheckboxCard };
