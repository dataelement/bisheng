import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import { Button } from '../Button/Button';
import { Input } from '../Input/Input';
import { Tooltip } from '../Tooltip/Tooltip';
import type { CascaderColumn } from './CascaderPanel';
import type { CascaderEntry } from './utils';

export interface CascaderMobilePanelProps {
  treeId: string;
  activeDescendant: string;
  multiple: boolean;
  searchable: boolean;
  keyword: string;
  columns: CascaderColumn[];
  searchResults: CascaderEntry[] | null;
  backLabel: string;
  clearLabel: string;
  searchPlaceholder: string;
  panel: React.ReactNode;
  onBack: () => void;
  onKeyword: (value: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
}

export function CascaderMobilePanel({
  treeId,
  activeDescendant,
  multiple,
  searchable,
  keyword,
  columns,
  searchResults,
  backLabel,
  clearLabel,
  searchPlaceholder,
  panel,
  onBack,
  onKeyword,
  onKeyDown,
}: CascaderMobilePanelProps) {
  const lastColumn = columns[columns.length - 1];
  const currentParent = lastColumn?.parentOptions[lastColumn.parentOptions.length - 1];

  return (
    <>
      {columns.length > 1 && searchResults === null && (
        <div className="flex min-h-8 shrink-0 items-center gap-1 px-1.5 py-1 text-control">
          <Tooltip content={backLabel}>
            <Button
              size="small"
              variant="text"
              color="default"
              iconOnly
              aria-label={backLabel}
              onMouseDown={(event) => event.preventDefault()}
              className="shrink-0"
              onClick={onBack}
            >
              <Outlined.Left aria-hidden />
            </Button>
          </Tooltip>
          {currentParent && (
            <span className="min-w-0 flex-1 truncate text-text-2">
              {currentParent.label}
            </span>
          )}
        </div>
      )}
      {searchable && (
        <div className="shrink-0 p-1.5">
          <Input
            role="combobox"
            aria-label={searchPlaceholder}
            aria-expanded
            aria-controls={treeId}
            aria-activedescendant={activeDescendant}
            aria-autocomplete="list"
            value={keyword}
            placeholder={searchPlaceholder}
            allowClear
            clearLabel={clearLabel}
            onChange={(event) => onKeyword(event.target.value)}
            onKeyDown={onKeyDown}
            className="w-full"
          />
        </div>
      )}
      <div
        id={treeId}
        role="tree"
        aria-multiselectable={multiple || undefined}
        className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain"
      >
        {panel}
      </div>
    </>
  );
}
