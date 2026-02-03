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
import { useCallback, useEffect, useState } from 'react';
import { NotificationSeverity, type AugmentedColumnDef } from '~/common';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
  building
}: DataTableProps<TData, TValue>) {
  const localize = useLocalize();
  const [isDeleting, setIsDeleting] = useState(false);
  const [rowSelection, setRowSelection] = useState({});
  const [sorting, setSorting] = useState<SortingState>([]);
  const isSmallScreen = useMediaQuery('(max-width: 768px)');
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const { deleteFiles } = useDeleteFilesFromTable(() => setIsDeleting(false));

  // 重复文件相关状态
  const [repeatFiles, setRepeatFiles] = useState([]);
  const [retryLoad, setRetryLoad] = useState(false);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [infoId, setInfoId] = useState('');
  const [fileUrl, setFileUrl] = useState('');
  const handleSearch = useCallback(
    debounce((event: any) => {
      onSearch(event.target.value);
    }, 300),
    [onSearch],
  );
  useEffect(() => {
    const fetchUserInfo = async () => {
      const res = await dataService.getUserInfo();
      setInfoId(res.data[0].id);
    }
    fetchUserInfo();
  }, [])

  const [loading, setLoading] = useState(false);
  const { showToast } = useToast();

  const unRetry = () => {
    setRepeatFiles([]);
    setPendingFiles([]);
    setLoading(false);
  };

  const onRetry = async (files) => {
    setRetryLoad(true);
    try {
      const formData = new FormData();
      formData.append('retry', 'true');

      files.forEach(file => {
        if (file.file) {
          formData.append('file', file.file);
        }
        if (file.name) {
          formData.append('filename', file.name);
        }
      });
      const fileList = repeatFiles.map(repeatFile => ({
        file_path: repeatFile.file_path,
        excel_rule: repeatFile.fileType === 'file' ? {} : {
          "append_header": true,
          "header_end_row": 1,
          "header_start_row": 1,
          "slice_length": 10
        }
      }));

      // 一次上传所有重复文件
      const params = {
        knowledge_id: infoId,
        file_list: fileList, // 数组，包含多个重复文件
        separator: ["\n\n", "\n"],
        separator_rule: ["after", "after"],
        chunk_size: 1000,
        chunk_overlap: 100,
        retain_images: true,
        enable_formula: true,
        force_ocr: true,
        fileter_page_header_footer: true
      };

      const uploadRes = await dataService.subUploadLibFile(params);

      if (uploadRes.status_code === 200) {
        showToast({
          message: localize('com_tools_file_upload_success', { count: repeatFiles.length }),
          severity: NotificationSeverity.SUCCESS,
        });
        onUpload();
      } else {
        showToast({
          message: uploadRes.status_message || localize('com_tools_file_upload_failed'),
          severity: NotificationSeverity.ERROR,
        });
      }
    } catch (error) {
      console.error('com_tools_file_upload_failed:', error);
      showToast({
        message: localize('com_tools_file_upload_failed') + error.message,
        severity: NotificationSeverity.ERROR,
      });
    } finally {
      setRetryLoad(false);
      setRepeatFiles([]);
      setPendingFiles([]);
      setLoading(false);
    }
  };

  const handleUpload = async (event) => {
    setLoading(true);
    const files = Array.from(event.target.files);

    // 在函数作用域内声明 duplicateFiles
    let duplicateFiles = [];

    if (!files || files.length === 0) {
      setLoading(false);
      return;
    }
    setPendingFiles(files.map(file => ({ file, name: file.name })));

    try {
      const nonDuplicateFiles = [];
      duplicateFiles = []; // 重置

      for (const file of files) {
        const formData = new FormData();
        formData.append('filename', file.name);
        formData.append('file', file);

        const repeatCheckRes = await dataService.repeatUpload(formData, infoId);

        if (repeatCheckRes.data?.repeat === true) {
          duplicateFiles.push({
            file,
            name: file.name,
            data: repeatCheckRes.data,
            file_path: repeatCheckRes.data.file_path,
          });
        } else {
          nonDuplicateFiles.push({
            file,
            name: file.name,
            file_path: repeatCheckRes.data.file_path,
          });
        }
      }

      if (duplicateFiles.length > 0) {
        setRepeatFiles(duplicateFiles.map(item => ({
          id: item.name,
          remark: localize('com_tools_knowledge_upload_remark'),
          file_path: item.file_path,
          fileType: 'file',
          file: item.file,
        })));
      }

      if (nonDuplicateFiles.length > 0) {
        let hasError = false;

        // 修改这里：将多个文件合并成一个数组上传
        const fileList = nonDuplicateFiles.map(fileInfo => ({
          file_path: fileInfo.file_path,
          excel_rule: fileInfo.file.type === 'file' ? {} : {
            "append_header": true,
            "header_end_row": 1,
            "header_start_row": 1,
            "slice_length": 10
          }
        }));

        // 一次上传所有非重复文件
        const params = {
          knowledge_id: infoId,
          file_list: fileList, // 这里是数组，包含多个文件
          separator: ["\n\n", "\n"],
          separator_rule: ["after", "after"],
          chunk_size: 1000,
          chunk_overlap: 100,
          retain_images: true,
          enable_formula: true,
          force_ocr: true,
          fileter_page_header_footer: true
        };

        const uploadRes = await dataService.subUploadLibFile(params);

        if (uploadRes.status_code === 500) {
          // 如果有错误，尝试解析哪些文件失败了
          showToast({
            message: localize('com_tools_file_upload_partial_error'),
            severity: NotificationSeverity.ERROR,
          });
          hasError = true;
        } else if (uploadRes.data?.remark) {
          showToast({
            message: uploadRes.data.remark || localize('com_tools_knowledge_upload_remark'),
            severity: NotificationSeverity.ERROR,
          });
          hasError = true;
        }

        if (!hasError) {
          showToast({
            message: localize('com_tools_file_upload_success', { count: nonDuplicateFiles.length }),
            severity: NotificationSeverity.SUCCESS,
          });
          onUpload();
        }
      }

    } catch (error) {
      console.error('com_tools_file_upload_failed:', error);
      showToast({
        message: localize('com_tools_file_upload_failed') + ': ' + error.message,
        severity: NotificationSeverity.ERROR,
      });
    } finally {
      if (duplicateFiles.length === 0) {
        setLoading(false);
      }
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
    manualPagination: true,
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
      <Dialog open={!!repeatFiles.length} onOpenChange={(b) => !b && setRepeatFiles([])}>
        <DialogContent className="sm:max-w-[425px]" close={false}>
          <DialogHeader>
            <DialogTitle>{localize('com_tools_file_detected')}</DialogTitle>
            <DialogDescription>
              {localize('com_tools_file_following')}
            </DialogDescription>
          </DialogHeader>
          <ul className="overflow-y-auto max-h-[400px] py-2">
            {repeatFiles.map(el => (
              <li key={el.id} className="py-1 text-red-500 text-sm">
                {el.remark}
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button className="h-8" variant="outline" onClick={unRetry}>
              {localize('com_tools_file_not_overwrite')}
            </Button>
            <Button
              className="h-8"
              disabled={retryLoad}
              onClick={() => onRetry(pendingFiles)}
            >
              {retryLoad && <span className="loading loading-spinner loading-xs mr-1"></span>}
              {localize('com_tools_file_overwrite')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
          {building ? (
            <Button onClick={() => {
              showToast({
                message: localize('com_tools_knowledge_rebuilding'),
                severity: NotificationSeverity.WARNING,
              });
            }}>
              {localize('com_knowledge_add_file')}
            </Button>
          ) : (
            <AttachFileButton disabled={loading} handleFileChange={handleUpload} />
          )}
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
            {`${table.getFilteredSelectedRowModel().rows.length}/${table.getFilteredRowModel().rows.length}`}
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
    </div>
  );
}
