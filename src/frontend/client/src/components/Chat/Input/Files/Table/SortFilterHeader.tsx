import { Column } from '@tanstack/react-table';
import { ListFilter, FilterX } from 'lucide-react';
import { ArrowDownIcon, ArrowUpIcon, CaretSortIcon } from '@radix-ui/react-icons';
import { Dropdown, DropdownItem, DropdownSeparator } from '@bisheng/ui';
import { Button } from '~/components/ui/Button';
import { useLocalize, TranslationKeys } from '~/hooks';
import { cn } from '~/utils';

interface SortFilterHeaderProps<TData, TValue> extends React.HTMLAttributes<HTMLDivElement> {
  title: string;
  column: Column<TData, TValue>;
  filters?: Record<string, string[] | number[]>;
  valueMap?: Record<any, TranslationKeys>;
}

export function SortFilterHeader<TData, TValue>({
  column,
  title,
  className = '',
  filters,
  valueMap,
}: SortFilterHeaderProps<TData, TValue>) {
  const localize = useLocalize();
  if (!column.getCanSort()) {
    return <div className={cn(className)}>{title}</div>;
  }

  return (
    <div className={cn('flex items-center space-x-2', className)}>
      <Dropdown
        menu={
          <>
            <DropdownItem icon={<ArrowUpIcon />} onSelect={() => column.toggleSorting(false)}>
              {localize('com_ui_ascending')}
            </DropdownItem>
            <DropdownItem icon={<ArrowDownIcon />} onSelect={() => column.toggleSorting(true)}>
              {localize('com_ui_descending')}
            </DropdownItem>
            {filters && <DropdownSeparator />}
            {filters &&
              Object.entries(filters).map(([key, values]) =>
                values.map((value?: string | number) => {
                  const translationKey = valueMap?.[value ?? ''];
                  const filterValue =
                    translationKey != null && translationKey.length
                      ? localize(translationKey)
                      : String(value);
                  if (!filterValue) {
                    return null;
                  }
                  return (
                    <DropdownItem
                      key={`${key}-${value}`}
                      icon={<ListFilter />}
                      onSelect={() => {
                        column.setFilterValue(value);
                      }}
                    >
                      {filterValue}
                    </DropdownItem>
                  );
                }),
              )}
            {filters && (
              <DropdownItem
                icon={<FilterX />}
                disabled={!column.getIsFiltered()}
                onSelect={() => {
                  column.setFilterValue(undefined);
                }}
              >
                {localize('com_ui_show_all')}
              </DropdownItem>
            )}
          </>
        }
      >
        <Button
          variant="ghost"
          className="px-2 py-0 text-xs hover:bg-surface-hover data-[state=open]:bg-surface-hover sm:px-2 sm:py-2 sm:text-sm"
        >
          <span>{title}</span>
          {column.getIsFiltered() ? (
            <ListFilter className="icon-sm ml-2 text-muted-foreground/70" />
          ) : (
            <ListFilter className="icon-sm ml-2 opacity-30" />
          )}
          {(() => {
            const sortState = column.getIsSorted();
            if (sortState === 'desc') {
              return <ArrowDownIcon className="icon-sm ml-2" />;
            }
            if (sortState === 'asc') {
              return <ArrowUpIcon className="icon-sm ml-2" />;
            }
            return <CaretSortIcon className="icon-sm ml-2" />;
          })()}
        </Button>
      </Dropdown>
    </div>
  );
}
