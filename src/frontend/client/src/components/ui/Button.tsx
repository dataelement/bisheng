import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';
import { Outlined } from 'bisheng-icons';
import { cn } from '~/utils';

/**
 * Button — design-system base component (docs-ui-refactor/组件-Button按钮.md).
 *
 * New API is the antd-style dual axis: `color` (primary/default/danger) ×
 * `variant` (solid/outlined/filled/text/link) × `size` (small/medium/large),
 * plus `iconOnly` for icon buttons and `shape` (square/circle, circle being
 * icon-only). All colors go through semantic
 * tokens (`btn-*` in tailwind.config / style.css, brand via `blue-*`); hover
 * states are disabled on touch (§5.5) and disabled/loading are uniform (§5.2).
 *
 * The legacy shadcn API (`variant="outline" | "ghost" | ...`, `size="sm" |
 * "icon" | ...`) still works through an automatic mapping (§6.3) so existing
 * call sites keep rendering; they will be migrated batch-by-batch and the
 * mapping removed afterwards.
 */

type ButtonColor = 'primary' | 'default' | 'danger';
type ButtonVariant = 'solid' | 'outlined' | 'filled' | 'text' | 'link';
type ButtonSize = 'small' | 'medium' | 'large';
type ButtonShape = 'square' | 'circle';

/** @deprecated Legacy single-axis variants — auto-mapped to color×variant (§6.3). */
type LegacyVariant =
  | 'default'
  | 'destructive'
  | 'outline'
  | 'secondary'
  | 'secondaryBrand'
  | 'ghost'
  | 'submit';
/** @deprecated Legacy sizes — auto-mapped (`icon` → medium + iconOnly). */
type LegacySize = 'default' | 'sm' | 'lg' | 'icon';

const buttonStyles = cva(
  // Disabled is uniform across every combo (§5.2) and must beat both the
  // combo colors and legacy className overrides, hence the `!` importants.
  // `relative` anchors the .btn-touch-hit ::after hot zone (style.css).
  // Weight 400 across all sizes/types (§3.1) — heavier weights are not a knob.
  'relative inline-flex items-center justify-center whitespace-nowrap font-normal transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:!border-btn-disabled-border disabled:!bg-black/[0.04] disabled:!text-black/25 [&_svg]:shrink-0',
  {
    variants: {
      // Color axis only carries what is combo-independent (focus ring, §5.2).
      color: {
        primary: 'focus-visible:ring-blue-500/40',
        default: 'focus-visible:ring-blue-500/40',
        danger: 'focus-visible:ring-btn-danger/40',
      },
      variant: {
        solid: '',
        outlined: 'border bg-white',
        filled: '',
        text: '',
        link: 'underline-offset-4',
      },
      // Heights/radii per §2 (24/32/40, 4/6/8px). Font sizes reference the
      // PRIMITIVE type scale vars on purpose: the semantic --text-body remaps
      // 14→16 under 768px, but control text must not follow (§5.5 / 适配原则 §3).
      // Icon size is one 14/16/18 ladder for BOTH icon-only and text+icon (§3.2/3.3).
      // Horizontal padding here is the borderless value (8/16/16); bordered
      // variants override to 7/15/15 in compoundVariants (visual-width parity).
      size: {
        small:
          'h-6 gap-1 rounded px-2 text-[length:var(--font-size-3)] leading-[var(--line-height-3)] [&_svg]:size-3.5',
        medium:
          'btn-touch-hit h-8 gap-2 rounded-md px-4 text-[length:var(--font-size-3)] leading-[var(--line-height-3)] [&_svg]:size-4',
        large:
          'h-10 gap-2 rounded-lg px-4 text-[length:var(--font-size-4)] leading-[var(--line-height-4)] [&_svg]:size-[18px]',
      },
      // `circle` is declared AFTER `size` so its rounded-full wins the merge
      // over the per-size radius; resolveVariants restricts it to icon-only (§1).
      shape: {
        square: '',
        circle: 'rounded-full',
      },
      iconOnly: {
        true: '',
        false: '',
      },
    },
    compoundVariants: [
      /* ---- color × variant matrix (§5.2; combos the spec leaves implicit
             follow the same ramp logic: hover one step, active one deeper).
             Active steps are TOUCH-ONLY (coarse-pointer): on hover-capable
             devices a pressed button keeps its hover color — no click flash;
             on touch, where hover is disabled, active is the only feedback. ---- */
      {
        color: 'primary',
        variant: 'solid',
        // btn-brand-primary = green-theme !important override (style.css) —
        // kept as agreed tech debt until the theme mechanism is reworked (§6.2).
        class:
          'btn-brand-primary bg-blue-500 text-white hover:bg-blue-400 coarse-pointer:active:bg-blue-600',
      },
      {
        color: 'primary',
        variant: 'outlined',
        // Outlined hover is a faint tint of the button's own palette, border/
        // text unchanged (§5.2) — same shape as default outlined's gray tint.
        class: 'border-blue-500 text-blue-500 hover:bg-blue-50 coarse-pointer:active:bg-blue-100',
      },
      {
        color: 'primary',
        variant: 'filled',
        class: 'bg-blue-50 text-blue-600 hover:bg-blue-100 coarse-pointer:active:bg-blue-200',
      },
      {
        color: 'primary',
        variant: 'text',
        class: 'text-blue-500 hover:bg-blue-50 coarse-pointer:active:bg-blue-100',
      },
      {
        color: 'primary',
        variant: 'link',
        class:
          'text-blue-500 hover:text-blue-400 hover:underline coarse-pointer:active:text-blue-600',
      },
      {
        color: 'default',
        variant: 'solid',
        class:
          'bg-btn-gray-text text-white hover:bg-btn-gray-text/90 coarse-pointer:active:bg-btn-gray-text/80',
      },
      {
        color: 'default',
        variant: 'outlined',
        class:
          'border-btn-gray-border text-btn-gray-text hover:bg-btn-fill-1 coarse-pointer:active:bg-btn-fill-2',
      },
      {
        color: 'default',
        variant: 'filled',
        class:
          'bg-btn-fill-2 text-btn-gray-text hover:bg-btn-fill-3 coarse-pointer:active:bg-btn-fill-4',
      },
      {
        color: 'default',
        variant: 'text',
        class:
          'text-btn-gray-text hover:bg-btn-fill-1 coarse-pointer:active:bg-btn-fill-2',
      },
      {
        color: 'default',
        variant: 'link',
        class:
          'text-btn-gray-text hover:text-btn-gray-text/80 hover:underline coarse-pointer:active:text-btn-gray-text',
      },
      {
        color: 'danger',
        variant: 'solid',
        class:
          'bg-btn-danger text-white hover:bg-btn-danger-hover coarse-pointer:active:bg-btn-danger-active',
      },
      {
        color: 'danger',
        variant: 'outlined',
        // Same faint-tint hover as primary outlined, on the red alpha ladder.
        class:
          'border-btn-danger text-btn-danger hover:bg-btn-danger/10 coarse-pointer:active:bg-btn-danger/[0.15]',
      },
      {
        color: 'danger',
        variant: 'filled',
        class:
          'bg-btn-danger/10 text-btn-danger hover:bg-btn-danger/[0.15] coarse-pointer:active:bg-btn-danger/20',
      },
      {
        color: 'danger',
        variant: 'text',
        class:
          'text-btn-danger hover:bg-btn-danger/10 coarse-pointer:active:bg-btn-danger/[0.15]',
      },
      {
        color: 'danger',
        variant: 'link',
        class:
          'text-btn-danger hover:text-btn-danger-hover hover:underline coarse-pointer:active:text-btn-danger-active',
      },
      /* ---- bordered padding 7/15/15 incl. 1px border (§2 visual parity) ---- */
      { variant: 'outlined', size: 'small', class: 'px-[7px]' },
      { variant: 'outlined', size: ['medium', 'large'], class: 'px-[15px]' },
      /* ---- icon-only squares 24/32/40 (§3.2, icon ladder shared with the
              size axis); every size gets the ≥44px touch hot zone (§5.5) ---- */
      { iconOnly: true, size: 'small', class: 'btn-touch-hit w-6 px-0' },
      { iconOnly: true, size: 'medium', class: 'w-8 px-0' },
      { iconOnly: true, size: 'large', class: 'btn-touch-hit w-10 px-0' },
    ],
    // Bare <Button> keeps its historical primary-solid look (§6.3).
    defaultVariants: {
      color: 'primary',
      variant: 'solid',
      size: 'medium',
      shape: 'square',
      iconOnly: false,
    },
  },
);

export interface ButtonStyleProps {
  // `(string & {})` keeps the three literals in autocomplete while still
  // accepting `{...props}` spreads that carry the native HTML `color` attr
  // (e.g. TooltipAnchor render props); non-axis strings are ignored at runtime.
  color?: ButtonColor | (string & {});
  variant?: ButtonVariant | LegacyVariant;
  size?: ButtonSize | LegacySize;
  /** `circle` renders a full circle — icon-only buttons ONLY (§1); ignored otherwise. */
  shape?: ButtonShape;
  /** Square icon-only button (§3.2) — must ship an `aria-label` + Tooltip. */
  iconOnly?: boolean;
}

function isButtonColor(value: unknown): value is ButtonColor {
  return value === 'primary' || value === 'default' || value === 'danger';
}

const LEGACY_VARIANT_MAP: Record<string, { color: ButtonColor; variant: ButtonVariant }> = {
  default: { color: 'primary', variant: 'solid' },
  submit: { color: 'primary', variant: 'solid' },
  destructive: { color: 'danger', variant: 'solid' },
  outline: { color: 'default', variant: 'outlined' },
  secondary: { color: 'default', variant: 'filled' },
  secondaryBrand: { color: 'primary', variant: 'filled' },
  ghost: { color: 'default', variant: 'text' },
  // Bare `variant="link"` predates the color axis — keep its primary look.
  link: { color: 'primary', variant: 'link' },
};

function resolveVariants({ color: rawColor, variant, size, shape, iconOnly }: ButtonStyleProps) {
  const color = isButtonColor(rawColor) ? rawColor : undefined;
  let resolvedColor = color;
  let resolvedVariant = variant as ButtonVariant | undefined;
  // Legacy values only kick in while the new `color` axis is absent — any
  // explicit `color` means the caller is on the new dual-axis API.
  if (color === undefined && variant !== undefined && variant in LEGACY_VARIANT_MAP) {
    ({ color: resolvedColor, variant: resolvedVariant } = LEGACY_VARIANT_MAP[variant]);
  } else if (color !== undefined && variant === undefined) {
    // New-API ergonomics matching the §1 named types: <Button color="default">
    // is THE default button (outlined), primary/danger default to solid.
    resolvedVariant = color === 'default' ? 'outlined' : 'solid';
  }

  let resolvedSize: ButtonSize | undefined;
  let resolvedIconOnly = iconOnly;
  switch (size) {
    case 'default':
    case 'sm':
      resolvedSize = 'medium';
      break;
    case 'lg':
      resolvedSize = 'large';
      break;
    case 'icon':
      resolvedSize = 'medium';
      resolvedIconOnly = iconOnly ?? true;
      break;
    default:
      resolvedSize = size;
  }

  return {
    color: resolvedColor,
    variant: resolvedVariant,
    size: resolvedSize,
    // Circle is an icon-only privilege (§1) — text buttons fall back to square.
    shape: shape === 'circle' && resolvedIconOnly ? ('circle' as const) : ('square' as const),
    iconOnly: resolvedIconOnly,
  };
}

/** Class-only entry point (for <a>/Slot call sites); accepts both APIs. */
export function buttonVariants(props: ButtonStyleProps & { className?: string } = {}) {
  const { className, ...styleProps } = props;
  return buttonStyles({ ...resolveVariants(styleProps), className });
}

export interface ButtonProps
  // Native `color` attr is shadowed by the color axis.
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'color'>,
    ButtonStyleProps {
  asChild?: boolean;
  /** Single leading icon (§3.3, one icon max); replaced by the spinner while loading. */
  icon?: React.ReactNode;
  /**
   * Built-in loading state (§5.2): spinner takes the icon slot, whole button
   * at opacity .65 and not clickable. Do NOT pass your own Spinner.
   */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      color,
      variant,
      size,
      shape,
      iconOnly,
      icon,
      loading = false,
      asChild = false,
      children,
      ...props
    },
    ref,
  ) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        ref={ref}
        aria-busy={loading || undefined}
        className={cn(
          buttonVariants({ color, variant, size, shape, iconOnly }),
          loading && 'pointer-events-none opacity-65',
          className,
        )}
        {...props}
      >
        {asChild ? (
          // Slot requires a single element child — icon/spinner injection is
          // skipped; asChild callers render their own content.
          children
        ) : (
          <>
            {loading ? <Outlined.Loading className="animate-spin" /> : icon}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = 'Button';

export { Button };
