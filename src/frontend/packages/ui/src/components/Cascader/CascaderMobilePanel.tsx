import * as React from 'react';
import { createPortal } from 'react-dom';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Button } from '../Button/Button';
import { Input } from '../Input/Input';
import { panelSurfaceClass, type PanelRadius } from '../shared/menuSurface';
import type { CascaderColumn } from './CascaderPanel';
import type { CascaderEntry } from './utils';

export interface CascaderMobilePanelProps {
  open: boolean;
  treeId: string;
  multiple: boolean;
  searchable: boolean;
  keyword: string;
  columns: CascaderColumn[];
  searchResults: CascaderEntry[] | null;
  panelRadius: PanelRadius;
  panelClassName?: string;
  backLabel: string;
  doneLabel: string;
  clearLabel: string;
  searchPlaceholder: string;
  panel: React.ReactNode;
  onBack: () => void;
  onKeyword: (value: string) => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
  onClose: () => void;
}

export function CascaderMobilePanel({
  open,
  treeId,
  multiple,
  searchable,
  keyword,
  columns,
  searchResults,
  panelRadius,
  panelClassName,
  backLabel,
  doneLabel,
  clearLabel,
  searchPlaceholder,
  panel,
  onBack,
  onKeyword,
  onKeyDown,
  onClose,
}: CascaderMobilePanelProps) {
  if (!open || typeof document === 'undefined') return null;
  const lastColumn = columns[columns.length - 1];
  const currentParent = lastColumn?.parentOptions[lastColumn.parentOptions.length - 1];

  return createPortal(
    <div className="fixed inset-0 z-popover" role="presentation">
      <div className="absolute inset-0 bg-black/40" onMouseDown={onClose} />
      <div
        data-state="open"
        data-side="bottom"
        className={panelSurfaceClass(
          panelRadius,
          cn(
            'absolute inset-x-0 bottom-0 flex max-h-[80vh] flex-col rounded-none rounded-t-xl',
            panelClassName,
          ),
        )}
      >
        {(columns.length > 1 || searchable) && (
          <div className="flex min-h-12 items-center gap-2 border-b border-border-base px-3 py-2">
            {columns.length > 1 && searchResults === null && (
              <button
                type="button"
                aria-label={backLabel}
                className="btn-touch-hit flex size-8 shrink-0 items-center justify-center rounded-md text-text-2 outline-none hover:bg-fill-2 focus-visible:shadow-focus coarse-pointer:active:bg-fill-2"
                onClick={onBack}
              >
                <Outlined.Left className="size-4" aria-hidden />
              </button>
            )}
            {currentParent && searchResults === null && (
              <span className="min-w-0 flex-1 truncate font-medium text-text-1">
                {currentParent.label}
              </span>
            )}
            {searchable && (
              <Input
                value={keyword}
                placeholder={searchPlaceholder}
                allowClear
                clearLabel={clearLabel}
                onChange={(event) => onKeyword(event.target.value)}
                onKeyDown={onKeyDown}
                className={cn(currentParent && searchResults === null ? 'w-1/2' : 'flex-1')}
              />
            )}
          </div>
        )}
        <div
          id={treeId}
          role="tree"
          aria-multiselectable={multiple || undefined}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        >
          {panel}
        </div>
        {multiple && (
          <div className="border-t border-border-base p-3 pb-[calc(12px+env(safe-area-inset-bottom))]">
            <Button className="w-full" onClick={onClose}>
              {doneLabel}
            </Button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
