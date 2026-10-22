import { ArrowDownIcon, ArrowUpIcon, CaretSortIcon, EyeNoneIcon } from '@radix-ui/react-icons';
import { Column } from '@tanstack/react-table';

import { cn } from '~/utils';
import { Button } from './Button';
import { Dropdown, DropdownItem, DropdownSeparator } from '@bisheng/ui';

interface DataTableColumnHeaderProps<TData, TValue> extends React.HTMLAttributes<HTMLDivElement> {
  column: Column<TData, TValue>;
  title: string;
}

export function DataTableColumnHeader<TData, TValue>({
  column,
  title,
  className = '',
}: DataTableColumnHeaderProps<TData, TValue>) {
  if (!column.getCanSort()) {
    return <div className={cn(className)}>{title}</div>;
  }

  return (
    <div className={cn('flex items-center space-x-2', className)}>
      <Dropdown
        menu={
          <>
            <DropdownItem icon={<ArrowUpIcon />} onSelect={() => column.toggleSorting(false)}>
              Asc
            </DropdownItem>
            <DropdownItem icon={<ArrowDownIcon />} onSelect={() => column.toggleSorting(true)}>
              Desc
            </DropdownItem>
            <DropdownSeparator />
            <DropdownItem icon={<EyeNoneIcon />} onSelect={() => column.toggleVisibility(false)}>
              Hide
            </DropdownItem>
          </>
        }
      >
        <Button variant="ghost" size="sm" className="data-[state=open]:bg-accent -ml-3 h-8">
          <span>{title}</span>
          {column.getIsSorted() === 'desc' ? (
            <ArrowDownIcon className="ml-2 h-4 w-4" />
          ) : column.getIsSorted() === 'asc' ? (
            <ArrowUpIcon className="ml-2 h-4 w-4" />
          ) : (
            <CaretSortIcon className="ml-2 h-4 w-4" />
          )}
        </Button>
      </Dropdown>
    </div>
  );
}
