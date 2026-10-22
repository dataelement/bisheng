import * as React from 'react';
import cn from '../../utils/cn';
import { Button } from '../Button/Button';
import { Dropdown, DropdownChevron, type DropdownProps } from './Dropdown';

/**
 * DropdownButton — the split button of 组件-Dropdown下拉菜单.md §3.1: a main
 * action plus an arrow-only trigger holding "other ways to do the same thing"
 * (「发送 ▾」→ 定时发送). The two halves read as ONE button: a shared outline,
 * a 1px divider between them, radius on the outer corners only, and the same
 * size / color on both sides. Each half hovers and presses on its own — they
 * are two different actions.
 *
 * Only `outlined` and `solid`: those are the two forms whose divider has an
 * honest drawing (the shared border / a light line across the fill).
 */
export interface DropdownButtonProps
  extends Pick<
    DropdownProps,
    'menu' | 'trigger' | 'side' | 'panelRadius' | 'open' | 'defaultOpen' | 'onOpenChange'
  > {
  /** The main action's text. */
  children: React.ReactNode;
  /** The main action. The arrow never runs it — it only opens the menu. */
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  /** Accessible name of the arrow, e.g. "更多发送方式" (§3 — the arrow has no text of its own). */
  arrowLabel: string;
  color?: 'primary' | 'default' | 'danger';
  variant?: 'outlined' | 'solid';
  size?: 'small' | 'medium' | 'large';
  /** Leading icon of the main action. */
  icon?: React.ReactNode;
  /** Disables both halves. */
  disabled?: boolean;
  /** Main action only — the menu stays reachable while it runs. */
  loading?: boolean;
  /** The menu sits under the whole pair; aligning it to the arrow's end is the default. */
  align?: DropdownProps['align'];
  className?: string;
}

/** Inner corners square, outer corners keep the size's radius. */
const MAIN_HALF = 'rounded-r-none';
const ARROW_HALF = 'rounded-l-none';

/**
 * The divider. Outlined: the arrow slides 1px left so both borders collapse
 * into one line, and a hovered / focused half is raised so its edge wins.
 * Solid: a light line across the fill (white at 30% over any brand / red ramp).
 */
const DIVIDER = {
  outlined: '-ml-px hover:z-10 focus-visible:z-10',
  solid: 'border-l border-l-white/30',
} as const;

export function DropdownButton({
  children,
  onClick,
  arrowLabel,
  menu,
  color = 'default',
  variant = 'outlined',
  size = 'medium',
  icon,
  disabled = false,
  loading = false,
  align = 'end',
  className,
  ...dropdownProps
}: DropdownButtonProps) {
  return (
    <div className={cn('inline-flex items-stretch', className)}>
      <Button
        color={color}
        variant={variant}
        size={size}
        icon={icon}
        loading={loading}
        disabled={disabled}
        onClick={onClick}
        className={cn(MAIN_HALF, 'focus-visible:z-10')}
      >
        {children}
      </Button>
      <Dropdown menu={menu} align={align} disabled={disabled} {...dropdownProps}>
        <Button
          color={color}
          variant={variant}
          size={size}
          iconOnly
          disabled={disabled}
          aria-label={arrowLabel}
          className={cn(ARROW_HALF, DIVIDER[variant])}
        >
          <DropdownChevron />
        </Button>
      </Dropdown>
    </div>
  );
}
