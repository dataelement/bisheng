import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Checkbox } from '../Checkbox/Checkbox';
import { CONTROL_BASE, CONTROL_CHECKED, CONTROL_SIZE } from '../Selection/shared';
import { Tooltip } from '../Tooltip/Tooltip';
import {
  MENU_COLUMN,
  OPTION_CHECK,
  OPTION_ICON,
  PANEL_MESSAGE,
  optionClass,
  type PanelRadius,
} from '../shared/menuSurface';
import type { CascaderEntry } from './utils';
import type { CascaderOption, CascaderPath } from './types';

export interface CascaderColumn {
  parentPath: CascaderPath;
  parentOptions: CascaderOption[];
  options: CascaderOption[];
}

export type CascaderSelectionState = boolean | 'indeterminate';

export interface CascaderPanelProps {
  treeId: string;
  columns: CascaderColumn[];
  searchResults: CascaderEntry[] | null;
  activeLevel: number;
  activeIndex: number;
  expandedPath: CascaderPath;
  multiple: boolean;
  checkStrictly: boolean;
  panelRadius: PanelRadius;
  loading: boolean;
  loadingKeys: Set<string>;
  failedKeys: Set<string>;
  emptyText: React.ReactNode;
  noMatchText: React.ReactNode;
  loadingText: React.ReactNode;
  loadErrorText: React.ReactNode;
  separator: string;
  phone?: boolean;
  onActive: (level: number, index: number) => void;
  onOpen: (entry: CascaderEntry) => void;
  onHoverOpen: (entry: CascaderEntry) => void;
  onSelect: (entry: CascaderEntry) => void;
  getSelectionState: (entry: CascaderEntry) => CascaderSelectionState;
  canSelect: (entry: CascaderEntry) => boolean;
  getChildren: (option: CascaderOption, path: CascaderPath) => CascaderOption[] | undefined;
}

export function cascaderOptionId(treeId: string, level: number, index: number): string {
  return `${treeId}-level-${level}-option-${index}`;
}

interface OptionLabelProps {
  label: string;
}

function OptionLabel({ label }: OptionLabelProps) {
  const [clipped, setClipped] = React.useState(false);
  return (
    <Tooltip content={label} side="right" disabled={!clipped}>
      <span
        className="min-w-0 flex-1 truncate"
        onPointerEnter={(event) =>
          setClipped(event.currentTarget.scrollWidth > event.currentTarget.clientWidth)
        }
      >
        {label}
      </span>
    </Tooltip>
  );
}

interface StrictRadioProps {
  checked: boolean;
  disabled: boolean;
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
}

function StrictRadio({ checked, disabled, onClick }: StrictRadioProps) {
  return (
    <button
      type="button"
      tabIndex={-1}
      aria-hidden
      disabled={disabled}
      data-state={checked ? 'checked' : 'unchecked'}
      className={cn(
        'pointer-events-auto rounded-full',
        CONTROL_BASE,
        CONTROL_CHECKED,
        CONTROL_SIZE.medium,
      )}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      <span className={cn('size-2 rounded-full bg-current', !checked && 'invisible')} />
    </button>
  );
}

interface RowProps extends Omit<CascaderPanelProps, 'columns' | 'searchResults' | 'loading' | 'emptyText' | 'noMatchText' | 'loadingText'> {
  entry: CascaderEntry;
  option: CascaderOption;
  level: number;
  index: number;
  searchResult?: boolean;
}

function CascaderRow(props: RowProps) {
  const {
    treeId,
    entry,
    option,
    level,
    index,
    activeLevel,
    activeIndex,
    expandedPath,
    multiple,
    checkStrictly,
    panelRadius,
    loadingKeys,
    failedKeys,
    phone,
    searchResult,
    separator,
    onActive,
    onOpen,
    onHoverOpen,
    onSelect,
    getSelectionState,
    canSelect,
    getChildren,
  } = props;
  const children = getChildren(option, entry.path);
  const parent = !searchResult && (option.isLeaf === false || (children?.length ?? 0) > 0);
  const loading = loadingKeys.has(entry.key);
  const failed = failedKeys.has(entry.key);
  const selected = getSelectionState(entry);
  const selectable = canSelect(entry);
  const expanded = parent && expandedPath[level] === option.value;
  const active = activeLevel === level && activeIndex === index;
  const label = searchResult ? entry.options.map((item) => item.label).join(separator) : option.label;

  const handleRowClick = () => {
    if (option.disabled) return;
    onActive(level, index);
    if (parent) onOpen(entry);
    else if (selectable) onSelect(entry);
  };

  const handleControlClick = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (selectable && !option.disabled) onSelect(entry);
  };

  return (
    <div
      id={cascaderOptionId(treeId, level, index)}
      role="treeitem"
      aria-level={level + 1}
      aria-expanded={parent ? expanded : undefined}
      aria-selected={selected === true}
      aria-disabled={option.disabled || undefined}
      data-highlighted={active || expanded ? '' : undefined}
      data-disabled={option.disabled ? '' : undefined}
      className={optionClass(
        panelRadius,
        cn(phone && 'min-h-11 py-[11px]', !multiple && !checkStrictly && selected === true && 'font-medium'),
      )}
      onMouseDown={(event) => event.preventDefault()}
      onPointerMove={() => {
        if (!option.disabled) onActive(level, index);
      }}
      onPointerEnter={(event) => {
        if (parent && !option.disabled && event.pointerType !== 'touch') onHoverOpen(entry);
      }}
      onClick={handleRowClick}
    >
      {multiple && (
        <Checkbox
          checked={selected}
          disabled={option.disabled || !selectable}
          tabIndex={-1}
          aria-hidden
          onMouseDown={(event) => event.preventDefault()}
          onClick={handleControlClick}
        />
      )}
      {!multiple && checkStrictly && (
        <StrictRadio
          checked={selected === true}
          disabled={Boolean(option.disabled) || !selectable}
          onClick={handleControlClick}
        />
      )}
      {option.icon !== undefined && <span className={OPTION_ICON}>{option.icon}</span>}
      <OptionLabel label={label} />
      {loading ? (
        <Outlined.Loading className="size-4 shrink-0 animate-spin text-text-3" aria-hidden />
      ) : parent ? (
        <Outlined.Right
          className={cn('size-4 shrink-0 text-text-3', failed && 'text-warning')}
          aria-hidden
        />
      ) : !multiple && !checkStrictly && selected === true ? (
        <Outlined.Check className={OPTION_CHECK} aria-hidden />
      ) : null}
    </div>
  );
}

export function CascaderPanel(props: CascaderPanelProps) {
  const {
    columns,
    searchResults,
    loading,
    emptyText,
    noMatchText,
    loadingText,
    loadErrorText,
    failedKeys,
    phone,
  } = props;

  React.useEffect(() => {
    const node = document.getElementById(
      cascaderOptionId(props.treeId, props.activeLevel, props.activeIndex),
    );
    node?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [props.activeIndex, props.activeLevel, props.treeId]);

  if (loading) {
    return (
      <div className={PANEL_MESSAGE} role="status">
        <Outlined.Loading className="size-4 animate-spin" aria-hidden />
        {loadingText}
      </div>
    );
  }

  if (searchResults !== null) {
    if (searchResults.length === 0) return <div className={PANEL_MESSAGE}>{noMatchText}</div>;
    return (
      <div className={cn(MENU_COLUMN, phone && 'max-h-none')} role="group">
        {searchResults.map((entry, index) => {
          const option = entry.options[entry.options.length - 1];
          if (!option) return null;
          return (
            <CascaderRow
              key={entry.key}
              {...props}
              entry={entry}
              option={option}
              level={0}
              index={index}
              searchResult
            />
          );
        })}
      </div>
    );
  }

  if (columns[0]?.options.length === 0) return <div className={PANEL_MESSAGE}>{emptyText}</div>;

  const visibleColumns = phone ? columns.slice(-1) : columns;
  const levelOffset = phone ? columns.length - 1 : 0;
  return (
    <div role="group" className={cn('flex min-w-0', phone && 'block')}>
      {visibleColumns.map((column, visibleIndex) => {
        const level = visibleIndex + levelOffset;
        return (
          <React.Fragment key={JSON.stringify(column.parentPath)}>
            {visibleIndex > 0 && !phone && <div className="w-px shrink-0 bg-border-base" />}
            <div
              role="group"
              className={cn(MENU_COLUMN, 'min-w-40 flex-1 basis-40', phone && 'max-h-none')}
              style={phone ? undefined : { maxWidth: 240 }}
            >
              {column.options.map((option, index) => {
                const path = [...column.parentPath, option.value];
                const entry: CascaderEntry = {
                  key: JSON.stringify(path),
                  path,
                  options: [...column.parentOptions, option],
                };
                return (
                  <CascaderRow
                    key={entry.key}
                    {...props}
                    entry={entry}
                    option={option}
                    level={level}
                    index={index}
                  />
                );
              })}
              {Array.from(failedKeys).some((key) =>
                column.options.some((option) => key === JSON.stringify([...column.parentPath, option.value])),
              ) && <div className={cn(PANEL_MESSAGE, 'py-1.5 text-warning')}>{loadErrorText}</div>}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}
