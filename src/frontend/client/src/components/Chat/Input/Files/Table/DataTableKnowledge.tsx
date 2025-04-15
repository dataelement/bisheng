import type {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
} from '@tanstack/react-table';
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { dataService, FileContext } from '~/data-provider/data-provider/src';
import { debounce } from 'lodash';
import { useCallback, useState } from 'react';
import { NotificationSeverity, type AugmentedColumnDef } from '~/common';
import {
  Button,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '~/components/ui';
import { useMediaQuery, useToast } from '~/hooks';
import { useDeleteFilesFromTable } from '~/hooks/Files';
import useLocalize from '~/hooks/useLocalize';
import AttachFileButton from './AttachFileButton';

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
}

const contextMap = {
  [FileContext.filename]: 'com_ui_name',
  [FileContext.updatedAt]: 'com_ui_date',
  [FileContext.filterSource]: 'com_ui_storage',
  [FileContext.context]: 'com_ui_context',
  [FileContext.bytes]: 'com_ui_size',
};

type Style = {
  width?: number | string;
  maxWidth?: number | string;
  minWidth?: number | string;
  zIndex?: number;
};

export default function DataTableKnowledge<TData, TValue>({
  page,
  onPage,
  onSearch,
  onUpload,
  columns,
  data,
}: DataTableProps<TData, TValue>) {
  const localize = useLocalize();
  const [isDeleting, setIsDeleting] = useState(false);
  const [rowSelection, setRowSelection] = useState({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const isSmallScreen = useMediaQuery('(max-width: 768px)');
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const { deleteFiles } = useDeleteFilesFromTable(() => setIsDeleting(false));

  // const { handleFileChange, abortUpload } = useFileHandling();
  const handleSearch = useCallback(
    debounce((event: any) => {
      onSearch(event.target.value);
    }, 300),
    [onSearch],
  );

  const [loading, setLoading] = useState(false)
  const { showToast } = useToast()
  const handleUpload = async (event) => {
    setLoading(true); // 开始上传，设置 loading 为 true
    const files = Array.from(event.target.files); // 将 FileList 转换为数组
    try {
      // 遍历所有文件并上传
      for (const file of files) {
        const formData = new FormData();
        formData.append('filename', file.name);
        formData.append('file', file);
        await dataService.knowledgeUpload(formData); // 等待每个文件上传完成
        console.log(`File ${file.name} uploaded successfully`);
      }
    } catch (error) {
      showToast({
        message: 'Error uploading files:' + error,
        severity: NotificationSeverity.ERROR,
      })
      console.error('Error uploading files:', error);
    } finally {
      setLoading(false);
      onUpload()
    }
  };

  const table = useReactTable({
    data: data.list,
    columns,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onColumnFiltersChange: setColumnFilters,
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    getPaginationRowModel: getPaginationRowModel(),
    onRowSelectionChange: setRowSelection,
    manualPagination: true,  // 启用手动分页
    pageCount: Math.ceil(data.total / 20),
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
    },
  });

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2 py-2 sm:gap-4 sm:py-4">
        <div className='flex gap-2 sm:gap-4'>
          {/* <Input
            placeholder={localize('com_files_filter')}
            // value={(table.getColumn('file_name')?.getFilterValue() as string | undefined) ?? ''}
            onChange={handleSearch}
            // onChange={(event) =>  table.getColumn('file_name')?.setFilterValue(event.target.value)}
            className="flex-1 text-sm"
          /> */}
        </div>
        <div>
          <AttachFileButton disabled={loading} handleFileChange={handleUpload} />
        </div>
      </div>
      <div className="relative grid h-full max-h-[calc(100vh-20rem)] w-full flex-1 overflow-hidden overflow-x-auto overflow-y-auto rounded-md border border-black/10 dark:border-white/10">
        <Table className="w-full min-w-[300px] border-separate border-spacing-0">
          <TableHeader className="sticky top-0 z-50">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="border-b border-border-light">
                {headerGroup.headers.map((header, index) => {
                  const style: Style = {};
                  if (index === 0 && header.id === 'select') {
                    style.width = '35px';
                    style.minWidth = '35px';
                  } else if (header.id === 'filename') {
                    style.width = isSmallScreen ? '60%' : '40%';
                  } else {
                    style.width = isSmallScreen ? '20%' : '15%';
                  }

                  return (
                    <TableHead
                      key={header.id}
                      className="whitespace-nowrap bg-surface-secondary px-2 py-2 text-left text-sm font-medium text-text-secondary sm:px-4"
                      style={{ ...style }}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody className="w-full">
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && 'selected'}
                  className="border-b border-border-light transition-colors hover:bg-surface-secondary [tr:last-child_&]:border-b-0"
                >
                  {row.getVisibleCells().map((cell, index) => {
                    const maxWidth =
                      (cell.column.columnDef as AugmentedColumnDef<TData, TValue>).meta?.size ??
                      'auto';

                    const style: Style = {};
                    if (cell.column.id === 'filename') {
                      style.maxWidth = maxWidth;
                    } else if (index === 0) {
                      style.maxWidth = '20px';
                    }

                    return (
                      <TableCell
                        key={cell.id}
                        className="align-start overflow-x-auto px-2 py-1 text-xs sm:px-4 sm:py-2 sm:text-sm [tr[data-disabled=true]_&]:opacity-50"
                        style={style}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center">
                  {localize('com_files_no_results')}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-end gap-2 py-4">
        <div className="ml-2 flex-1 truncate text-xs text-muted-foreground sm:ml-4 sm:text-sm">
          {/* <span className="hidden sm:inline">
            {localize('com_files_number_selected', {
              0: `${table.getFilteredSelectedRowModel().rows.length}`,
              1: `${table.getFilteredRowModel().rows.length}`,
            })}
          </span> */}
          <span className="sm:hidden">
            {`${table.getFilteredSelectedRowModel().rows.length}/${table.getFilteredRowModel().rows.length
              }`}
          </span>
        </div>
        <div className="flex items-center space-x-1 pr-2 text-xs font-bold text-text-primary sm:text-sm">
          <span className="hidden sm:inline">{localize('com_ui_page')}</span>
          <span>{page}</span>
          <span>/</span>
          <span>{table.getPageCount()}</span>
        </div>
        <Button
          className="select-none"
          variant="outline"
          size="sm"
          onClick={() => onPage(page - 1)}
          disabled={page === 1}
        >
          {localize('com_ui_prev')}
        </Button>
        <Button
          className="select-none"
          variant="outline"
          size="sm"
          onClick={() => onPage(page + 1)}
          disabled={page === table.getPageCount()}
        >
          {localize('com_ui_next')}
        </Button>
      </div>
    </div >
  );
}
