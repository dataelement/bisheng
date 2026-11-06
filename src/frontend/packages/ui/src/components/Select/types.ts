import type * as React from 'react';
import type { InputSize, InputStatus } from '../Input/shared';
import type { PanelRadius, RadiusToken } from '../shared/menuSurface';
import type { SelectionVariant } from '../shared/SelectionTrigger';

export type SelectValue = string | number;

/** §3.1 — trigger form. Forms always use `outlined`. */
export type SelectVariant = SelectionVariant;

export interface SelectOption {
  value: SelectValue;
  /** Plain text: shown in the row and the trigger, and what search matches. */
  label: string;
  /** §5.2 — 16px leading icon. Either every option in a group has one or none do. */
  icon?: React.ReactNode;
  /** §5.2 — one line under the label, 12/20 hint gray. */
  description?: React.ReactNode;
  disabled?: boolean;
  /**
   * §5.3 — group title. Options sharing a title render under it, groups in
   * the order they first appear. Group only past ~8 options that sort naturally.
   */
  group?: string;
}

interface SelectBaseProps {
  options: SelectOption[];
  /** §4 — the Input ladder (24 / 32 / 40). The panel rows stay 32px regardless. */
  size?: InputSize;
  /** §7.1 — validation. Outlined only; ghost / icon carry no validation. */
  status?: InputStatus;
  /** §3.1 — `outlined` (default) for forms and filter bars, `ghost` / `icon` for toolbars. */
  variant?: SelectVariant;
  /** §5.4 — trigger radius rung; defaults to the size's own (sm / md / lg). Never override with className. */
  radius?: RadiusToken;
  /** §5.4 — panel radius rung, default `xl`; option rows follow it automatically. */
  panelRadius?: PanelRadius;
  /** §6.1 — "请选择 + 对象". Prefer a sensible default value over a placeholder. */
  placeholder?: string;
  disabled?: boolean;
  /** §7.1 — no arrow, never opens; the value can still be selected and copied. */
  readOnly?: boolean;
  /** §6.3 — type in the trigger to filter. Defaults to on past 10 options. */
  showSearch?: boolean;
  /**
   * §6.3 — server-side search: fires (debounced 300ms) with the keyword. When
   * set, local filtering is off unless `filterOption` says otherwise; pair it
   * with `loading` while the request is in flight.
   */
  onSearch?: (keyword: string) => void;
  /** Local filter. `true` = case-insensitive label match; `false` = show all. */
  filterOption?: boolean | ((keyword: string, option: SelectOption) => boolean);
  /** §6.4 — on for search / filter bars, off in real forms. */
  allowClear?: boolean;
  onClear?: () => void;
  /** §6.5 — the panel shows a spinner line instead of the list. */
  loading?: boolean;
  /** §6.5 — called once the list is scrolled to its end; show `loadingMore` meanwhile. */
  onLoadMore?: () => void;
  loadingMore?: boolean;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * The "arrow entry" of §3.1: the value is shown by an element next to it,
   * and this element only opens the panel. Must carry an `aria-label` that
   * names both the action and the current value. Search is off in this mode.
   */
  trigger?: React.ReactElement;
  /** Width and layout only — radius goes through `radius`, never a `rounded-*` class. */
  className?: string;
  /** Layout only — radius goes through `panelRadius`. */
  panelClassName?: string;
  id?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  /** Copy — the library holds none of its own. */
  emptyText?: React.ReactNode;
  noMatchText?: React.ReactNode;
  loadingText?: React.ReactNode;
  /** Accessible name of the clear button and of each tag's ×. */
  clearLabel?: string;
  removeLabel?: string;
}

export interface SelectSingleProps extends SelectBaseProps {
  multiple?: false;
  value?: SelectValue | null;
  defaultValue?: SelectValue | null;
  onChange?: (value: SelectValue | null, option: SelectOption | undefined) => void;
}

export interface SelectMultipleProps extends SelectBaseProps {
  /** §3 — check boxes in the panel, tags in the trigger, panel stays open while picking. */
  multiple: true;
  value?: SelectValue[];
  defaultValue?: SelectValue[];
  onChange?: (value: SelectValue[], options: SelectOption[]) => void;
}

export type SelectProps = SelectSingleProps | SelectMultipleProps;
