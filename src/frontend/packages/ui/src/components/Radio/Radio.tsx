import * as React from 'react';
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';
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
  FOCUS_RING_INSET,
  GROUP_LAYOUT,
  ROW_BASE,
  ROW_HOVER_CONTROL,
  ROW_TEXT,
  type SelectionSize,
} from '../Selection/shared';

/**
 * Radio — design-system base component (组件-Radio单选框.md v1).
 *
 * Picks ONE from a fully visible set (2–7 options; more means a Select), and
 * a checked option cannot be un-picked. Baked in per spec: the shared 14/16/18
 * ladder with the white inner dot at (outer − 8) (§3), the same gray→brand
 * chain as the checkbox (§5), the button-group skin as a `variant` riding the
 * Button height ladder (§2/§3), the card shell shared with CheckboxCard, and
 * roving-tabindex arrow-key movement via Radix (落地 §3).
 */

type RadioGroupVariant = 'default' | 'button';

interface RadioGroupContextValue {
  size: SelectionSize;
  variant: RadioGroupVariant;
}

const RadioGroupContext = React.createContext<RadioGroupContextValue>({
  size: 'medium',
  variant: 'default',
});

/** §3 — the white inner dot: outer − 8 → 6/8/10. */
const DOT_SIZE: Record<SelectionSize, string> = {
  small: 'size-1.5',
  medium: 'size-2',
  large: 'size-2.5',
};

/** §3 — button-group cells ride the Button ladder: 24/32/40 high, 8/16/16 padding. */
const BUTTON_CELL_SIZE: Record<SelectionSize, string> = {
  small: 'h-6 px-2 text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  medium: 'h-8 px-4 text-[length:var(--font-size-3)] leading-[var(--line-height-3)]',
  large: 'h-10 px-4 text-[length:var(--font-size-4)] leading-[var(--line-height-4)]',
};

/** §3 — group radius follows the Button ladder (4/6/8); only the outer corners round. */
const BUTTON_GROUP_RADIUS: Record<SelectionSize, string> = {
  small: 'rounded',
  medium: 'rounded-md',
  large: 'rounded-lg',
};

/**
 * §5 — the button-group state table: white + body text unchecked, light gray
 * wash on hover (text-button hover), brand text over the unified selection
 * tint when checked — never a solid brand fill (a switcher must not compete
 * with the primary button). Disabled reuses the button tokens.
 */
const BUTTON_CELL_BASE =
  'btn-touch-hit relative inline-flex cursor-pointer items-center justify-center whitespace-nowrap text-text-1 outline-none transition-colors data-[state=unchecked]:hover:bg-btn-fill-1 data-[state=checked]:bg-blue-500/[0.07] data-[state=checked]:text-blue-500 disabled:cursor-not-allowed disabled:!bg-btn-disabled-bg disabled:!text-btn-disabled-text';

export interface RadioGroupProps
  extends Omit<React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>, 'asChild'> {
  /** §3 — one ladder for both skins; medium is the default. */
  size?: SelectionSize;
  /** §2 — `button` renders the segmented skin for high-frequency switching. */
  variant?: RadioGroupVariant;
  /** §2 — default skin only: horizontal 16px gaps / vertical 8px. */
  direction?: 'horizontal' | 'vertical';
}

const RadioGroup = React.forwardRef<HTMLDivElement, RadioGroupProps>(
  ({ size = 'medium', variant = 'default', direction = 'horizontal', className, ...props }, ref) => {
    const context = React.useMemo(() => ({ size, variant }), [size, variant]);
    return (
      <RadioGroupContext.Provider value={context}>
        <RadioGroupPrimitive.Root
          ref={ref}
          className={cn(
            variant === 'button'
              ? // One shared outer border, 1px dividers between cells (§2);
                // overflow-hidden keeps cell corners inside the group radius.
                cn(
                  'inline-flex items-stretch divide-x divide-border-base overflow-hidden border border-border-base bg-bg-page',
                  BUTTON_GROUP_RADIUS[size],
                )
              : GROUP_LAYOUT[direction],
            className,
          )}
          {...props}
        />
      </RadioGroupContext.Provider>
    );
  },
);
RadioGroup.displayName = 'RadioGroup';

export interface RadioProps
  extends Omit<React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Item>, 'asChild'> {
  /** One secondary line under the label (§4) — default skin only. */
  description?: React.ReactNode;
  /** Class for the wrapping <label> when the option has text. */
  wrapperClassName?: string;
}

/** The circle itself — shared by the basic row and the card form. */
function renderControl(
  size: SelectionSize,
  className: string | undefined,
  inRow: boolean,
  props: Omit<RadioProps, 'description' | 'wrapperClassName' | 'className' | 'children'>,
  ref: React.ForwardedRef<HTMLButtonElement>,
) {
  return (
    <RadioGroupPrimitive.Item
      ref={ref}
      className={cn(
        'rounded-full',
        CONTROL_BASE,
        CONTROL_CHECKED,
        CONTROL_SIZE[size],
        inRow && CONTROL_OFFSET[size],
        inRow && ROW_HOVER_CONTROL,
        className,
      )}
      {...props}
    >
      {/* §5 — pure white dot via currentColor: white when checked, the disabled
          override grays it (选中禁用 = 浅灰底 + 灰内点). forceMount keeps the
          dot in the DOM so it can scale in AND out (200ms, same clock as the
          Switch thumb) — radix would otherwise unmount it and the dot pops. */}
      <RadioGroupPrimitive.Indicator
        forceMount
        className="flex scale-0 items-center justify-center transition-transform duration-200 data-[state=checked]:scale-100"
      >
        <span className={cn('rounded-full bg-current', DOT_SIZE[size])} />
      </RadioGroupPrimitive.Indicator>
    </RadioGroupPrimitive.Item>
  );
}

/**
 * One option. Under `variant="button"` it renders as a segmented cell; the
 * `description` prop is a default-skin affordance and is ignored there (§2:
 * cell copy is 2–4 characters).
 */
const Radio = React.forwardRef<HTMLButtonElement, RadioProps>(
  ({ description, wrapperClassName, className, children, ...props }, ref) => {
    const { size, variant } = React.useContext(RadioGroupContext);
    if (variant === 'button') {
      return (
        <RadioGroupPrimitive.Item
          ref={ref}
          className={cn(BUTTON_CELL_BASE, FOCUS_RING_INSET, BUTTON_CELL_SIZE[size], className)}
          {...props}
        >
          {children}
        </RadioGroupPrimitive.Item>
      );
    }
    const hasRow = children !== undefined || description !== undefined;
    const control = renderControl(size, className, hasRow, props, ref);
    if (!hasRow) return control;
    return (
      <label className={cn(ROW_BASE, ROW_TEXT[size], wrapperClassName)}>
        {control}
        <span className="flex min-w-0 flex-col">
          {children !== undefined && <span>{children}</span>}
          {description !== undefined && <span className={DESCRIPTION}>{description}</span>}
        </span>
      </label>
    );
  },
);
Radio.displayName = 'Radio';

export interface RadioCardProps extends Omit<RadioProps, 'wrapperClassName' | 'children'> {
  /** Card title — medium weight, body color (Checkbox §2). */
  label: React.ReactNode;
  /** Class for the card shell (the <label>). */
  wrapperClassName?: string;
}

/**
 * Card form — the shell is the checkbox card's (Checkbox §2, adopted by Radio
 * §2); only the control inside is a circle and selection is exclusive.
 */
const RadioCard = React.forwardRef<HTMLButtonElement, RadioCardProps>(
  ({ label, description, wrapperClassName, className, ...props }, ref) => {
    const { size } = React.useContext(RadioGroupContext);
    return (
      <label className={cn(CARD_SHELL, wrapperClassName)}>
        {renderControl(size, className, false, props, ref)}
        <span className={CARD_LABEL}>{label}</span>
        {description !== undefined && <span className={CARD_DESCRIPTION}>{description}</span>}
      </label>
    );
  },
);
RadioCard.displayName = 'RadioCard';

export { RadioGroup, Radio, RadioCard };
