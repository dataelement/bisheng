import type * as React from 'react';
import type { InputSize, InputStatus } from '../Input/shared';
import type { PanelRadius, RadiusToken } from '../shared/menuSurface';
import type { SelectionVariant } from '../shared/SelectionTrigger';

export type CascaderValue = string | number;
export type CascaderPath = CascaderValue[];
export type CascaderVariant = SelectionVariant;
export type CascaderExpandTrigger = 'click' | 'hover';

export interface CascaderOption {
  value: CascaderValue;
  label: string;
  children?: CascaderOption[];
  disabled?: boolean;
  /** `false` marks a parent whose children have not been loaded yet. */
  isLeaf?: boolean;
  icon?: React.ReactNode;
}

export type CascaderFilter = (keyword: string, path: CascaderOption[]) => boolean;
export type CascaderLoadData = (
  option: CascaderOption,
  path: CascaderOption[],
) => Promise<CascaderOption[]>;

interface CascaderBaseProps {
  options: CascaderOption[];
  size?: InputSize;
  status?: InputStatus;
  variant?: CascaderVariant;
  radius?: RadiusToken;
  panelRadius?: PanelRadius;
  placeholder?: string;
  disabled?: boolean;
  readOnly?: boolean;
  /** Allow selecting a parent independently. Parent and child values do not cascade in this mode. */
  checkStrictly?: boolean;
  expandTrigger?: CascaderExpandTrigger;
  showSearch?: boolean;
  onSearch?: (keyword: string) => void;
  /** `true` uses case-insensitive full-path matching; `false` leaves filtering to the caller. */
  filterOption?: boolean | CascaderFilter;
  loadData?: CascaderLoadData;
  onLoadError?: (error: unknown, option: CascaderOption, path: CascaderOption[]) => void;
  allowClear?: boolean;
  onClear?: () => void;
  loading?: boolean;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  trigger?: React.ReactElement;
  className?: string;
  panelClassName?: string;
  id?: string;
  separator?: string;
  /** Customize the single-selection label without changing the selected path. */
  displayRender?: (labels: string[], options: CascaderOption[]) => string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  emptyText?: React.ReactNode;
  noMatchText?: React.ReactNode;
  loadingText?: React.ReactNode;
  loadErrorText?: React.ReactNode;
  backLabel?: string;
  doneLabel?: string;
  clearLabel?: string;
  removeLabel?: string;
  searchPlaceholder?: string;
}

export interface CascaderSingleProps extends CascaderBaseProps {
  multiple?: false;
  value?: CascaderPath | null;
  defaultValue?: CascaderPath | null;
  onChange?: (value: CascaderPath | null, options: CascaderOption[]) => void;
}

export interface CascaderMultipleProps extends CascaderBaseProps {
  multiple: true;
  value?: CascaderPath[];
  defaultValue?: CascaderPath[];
  onChange?: (value: CascaderPath[], options: CascaderOption[][]) => void;
}

export type CascaderProps = CascaderSingleProps | CascaderMultipleProps;
