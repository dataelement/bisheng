import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/bs-ui/sheet';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { sopApi } from "@/controllers/API/linsight";
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { Check, ChevronDown, ChevronUp, Search, Star } from 'lucide-react';
import * as React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { LoadIcon } from '../bs-icons/loading';
import AutoPagination from '../bs-ui/pagination/autoPagination';
import SopMarkdown from './SopMarkdown';

interface SopRecord {
  id: number;
  name: string;
  description: string;
  user_id: number;
  content: string;
  rating: number;
  linsight_version_id: string;
  create_time: string;
  update_time: string;
  user_name: string;
}

export default function ImportFromRecordsDialog({ open, tools, onOpenChange,  onSuccess }) {
  const { toast } = useToast();
  const [searchTerm, setSearchTerm] = useState('');
  const [records, setRecords] = useState<SopRecord[]>([]);
  const [currentRecord, setCurrentRecord] = useState<SopRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [total, setTotal] = useState(0);
  const [sortConfig, setSortConfig] = useState({
    key: 'create_time',
    direction: 'desc' as 'asc' | 'desc'
  });
  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [duplicateNames, setDuplicateNames] = useState<string[]>([]);
  const [pageInputValue, setPageInputValue] = useState(page.toString());
  const [selectedRecordIds, setSelectedRecordIds] = useState<number[]>([]);

  // 获取SOP记录
  const fetchRecords = async () => {
    setLoading(true);
    try {
      const res = await sopApi.GetSopRecord({
        keyword: searchTerm,
        page,
        page_size: pageSize,
        sort: sortConfig.direction
      });

      console.log('API响应:', res);
      if (Array.isArray(res)) {
        setRecords(res);
        setTotal(res.length);
        setCurrentRecord(res[0] || null);
      }
      else if (res && Array.isArray(res.list)) {
        setRecords(res.list);
        setTotal(res.total || res.list.length);
        setCurrentRecord(res.list[0] || null);
      }
      else {
        throw new Error('API返回的数据结构不符合预期');
      }
    } catch (error) {
      console.error('获取数据失败:', error);
      toast({
        variant: 'error',
        description: error.message || '获取数据失败，请检查API响应结构'
      });
      setRecords([]);
      setTotal(0);
      setCurrentRecord(null);
    } finally {
      setLoading(false);
    }
  };
  // 初始化数据
  useEffect(() => {
    if (open) {
      fetchRecords();
    } else {
      setRecords([]);
      setSelectedRecordIds([]);
      setCurrentRecord(null);
      setSearchTerm('');
      setPage(1);
    }
  }, [open]);

  // 搜索和分页变化时重新获取数据
  useEffect(() => {
    const timer = setTimeout(() => {
      if (open) fetchRecords();
    }, 500);
    return () => clearTimeout(timer);
  }, [searchTerm, page, pageSize, sortConfig]);

  // 排序处理
  const sortedRecords = useMemo(() => {
    return [...records].sort((a, b) => {
      const aValue = a[sortConfig.key as keyof SopRecord];
      const bValue = b[sortConfig.key as keyof SopRecord];

      if (aValue === null || bValue === null) return 0;

      if (aValue < bValue) {
        return sortConfig.direction === 'asc' ? -1 : 1;
      }
      if (aValue > bValue) {
        return sortConfig.direction === 'asc' ? 1 : -1;
      }
      return 0;
    });
  }, [records, sortConfig]);

  // 处理页码输入变化
  const handlePageInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    if (value === '' || /^\d+$/.test(value)) {
      setPageInputValue(value);
    }
  };

  // 处理页码输入确认
  const handlePageInputConfirm = () => {
    if (pageInputValue === '') {
      setPageInputValue(page.toString());
      return;
    }

    const newPage = parseInt(pageInputValue);
    const maxPage = Math.max(1, Math.ceil(total / pageSize));

    if (newPage >= 1 && newPage <= maxPage) {
      setPage(newPage);
    } else {
      setPageInputValue(page.toString());
    }
  };

  // 处理键盘事件
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handlePageInputConfirm();
    }
  };

  // 处理记录选择和多选
  const handleSelectRecord = (record: SopRecord) => setCurrentRecord(record);

  const handleToggleSelect = (record: SopRecord, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedRecordIds(prev =>
      prev.includes(record.id)
        ? prev.filter(id => id !== record.id)
        : [...prev, record.id]
    );
    setCurrentRecord(record);
  };
  // 全选/取消全选当前页
  const handleToggleSelectAll = () => {
    const currentPageIds = records.map(r => r.id);
    const allSelected = currentPageIds.every(id => selectedRecordIds.includes(id));

    setSelectedRecordIds(prev =>
      allSelected
        ? prev.filter(id => !currentPageIds.includes(id))
        : [...new Set([...prev, ...currentPageIds])]
    );
  };

  const importSops = async (recordsToImport: SopRecord[], overwrite = false, saveNew = false) => {
    setLoading(true);
    try {
      const res = await captureAndAlertRequestErrorHoc(
        sopApi.SyncSopRecord({
          record_ids: recordsToImport.map(r => r.id),
          override: overwrite,
          save_new: saveNew
        })
      );

      if (res === false) return;

      if (res?.repeat_name) {
        setDuplicateNames(res.repeat_name);
        setDuplicateDialogOpen(true);
        return;
      }

      toast({ variant: 'success', description: '导入成功' });
      onOpenChange(false);
      onSuccess?.(); // 导入成功后调用回调
    } finally {
      setLoading(false);
    }
  };


  const markdownRef = useRef(null);
  useEffect(() => {
    markdownRef.current?.setValue(currentRecord?.content || '');
  }, [currentRecord])

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[87.5vw] min-w-[85vw]">
        <div className="flex h-full" onClick={e => e.stopPropagation()}>
          {/* 左侧记录列表 */}
          <div className="p-6 w-[50%]">
            <SheetHeader>
              <SheetTitle>从运行记录中导入SOP</SheetTitle>
            </SheetHeader>

            <div className="relative mt-6 mb-6 w-[80%]">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="搜索SOP"
                className="w-full pl-10 pr-4 py-2 rounded-md border focus:outline-none focus:ring-2 focus:ring-primary"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <div className="flex-1 overflow-y-auto h-[calc(100%-180px)]">
              {loading ? (
                <div className="flex justify-center items-center h-full">
                  <LoadIcon className="animate-spin w-8 h-8" />
                </div>
              ) : records.length === 0 ? (
                <div className="text-center text-muted-foreground py-4">
                  {searchTerm ? '没有找到匹配的记录' : '暂无运行记录'}
                </div>
              ) : (
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden flex flex-col h-full">
                  <div className="flex-1 overflow-y-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50 sticky top-0 z-10">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            <button
                              type="button"
                              className={`h-4 w-4 rounded border flex items-center justify-center ${records.length > 0 &&
                                records.every(r => selectedRecordIds.includes(r.id))
                                ? 'bg-blue-600 border-blue-600'
                                : 'bg-white border-gray-300'
                                } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
                              onClick={handleToggleSelectAll}
                              disabled={loading}
                            >
                              {records.length > 0 &&
                                records.every(r => selectedRecordIds.includes(r.id)) && (
                                  <Check className="w-3 h-3 text-white" />
                                )}
                            </button>
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            名称
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            <div className="flex items-center">
                              创建时间
                              <div className="flex flex-col ml-1">
                                <button onClick={() => setSortConfig({
                                  key: 'create_time',
                                  direction: 'asc'
                                })}>
                                  <ChevronUp className={`w-3 h-3 ${sortConfig.key === 'create_time' && sortConfig.direction === 'asc' ? 'text-blue-500' : 'text-gray-400'}`} />
                                </button>
                                <button onClick={() => setSortConfig({
                                  key: 'create_time',
                                  direction: 'desc'
                                })}>
                                  <ChevronDown className={`w-3 h-3 ${sortConfig.key === 'create_time' && sortConfig.direction === 'desc' ? 'text-blue-500' : 'text-gray-400'}`} />
                                </button>
                              </div>
                            </div>
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            创建用户
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            评分
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {sortedRecords.map((record) => (
                          <tr
                            key={record.id}
                            className={`cursor-pointer ${currentRecord?.id === record.id ? 'bg-blue-50' : ''}`}
                            onClick={() => handleSelectRecord(record)}
                          >
                            <td className="px-6 py-4 whitespace-nowrap">
                              <button
                                type="button"
                                className={`h-4 w-4 rounded border flex items-center justify-center ${selectedRecordIds.includes(record.id)
                                  ? 'bg-blue-600 border-blue-600'
                                  : 'bg-white border-gray-300'
                                  } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
                                onClick={(e) => !loading && handleToggleSelect(record, e)}
                                disabled={loading}
                              >
                                {selectedRecordIds.includes(record.id) && (
                                  <Check className="w-3 h-3 text-white" />
                                )}
                              </button>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap max-w-[200px]">
                              <div className="text-sm font-medium text-gray-900 truncate">
                                {record.name}
                              </div>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {new Date(record.create_time).toLocaleString()}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {record.user_name}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap">
                              <div className="flex items-center">
                                {[...Array(5)].map((_, i) => (
                                  <Star
                                    key={i}
                                    className={`w-4 h-4 ${i < (record.rating || 0) ? 'text-yellow-400' : 'text-gray-300'}`}
                                  />
                                ))}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {records.length > 0 && (
                    <div className="px-6 py-3 flex items-center justify-between border-t border-gray-200">
                      <div className="flex items-center">
                        <span className="text-sm text-gray-700">
                          共 {total} 条记录
                        </span>
                      </div>
                      <div className="flex items-center ml-4">
                        <AutoPagination
                          page={page}
                          pageSize={pageSize}
                          total={total}
                          onChange={setPage}
                        />
                        <span className="text-sm text-gray-700 mr-2 whitespace-nowrap">跳至</span>
                        <input
                          type="number"
                          min="1"
                          max={Math.max(1, Math.ceil(total / pageSize))}
                          value={pageInputValue}
                          onChange={handlePageInputChange}
                          onBlur={handlePageInputConfirm}
                          onKeyDown={handleKeyDown}
                          className="w-16 px-2 py-1 border rounded text-sm text-center"
                          disabled={loading}
                        />
                        <span className="text-sm text-gray-700 ml-2 whitespace-nowrap">
                          页
                        </span>
                        {loading && <LoadIcon className="animate-spin w-4 h-4 ml-2" />}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-start mt-4">
              <span>已选择 {selectedRecordIds.length} 项</span>
              <Button
                onClick={() => {
                  const selected = records.filter(r => selectedRecordIds.includes(r.id));
                  importSops(selected, false, false);
                }}
                disabled={selectedRecordIds.length === 0 || loading}
                className="ml-4"
              >
                {loading ? '导入中...' : `批量导入`}
              </Button>
            </div>
          </div>

          {/* 右侧预览区域 */}
          <div className="flex-1 bg-[#fff] p-6 h-full flex flex-col w-[50%]">
            {currentRecord ? (
              <>
                <div className="mb-4">
                  <h3 className="text-lg font-semibold truncate">{currentRecord.name}</h3>
                  <p className="text-muted-foreground truncate">{currentRecord.description}</p>
                </div>
                <div className="flex-1 overflow-y-auto bg-gray-50 rounded-md">
                  <SopMarkdown
                    ref={markdownRef}
                    defaultValue={currentRecord?.content}
                    tools={tools}
                    height='h-[calc(100vh-170px)]'
                    className="h-full"
                    disabled={true}
                  />
                </div>
                <div className="flex justify-start gap-2 pt-4">
                  <Button
                    onClick={() => {
                      if (!currentRecord) return;

                      // 直接尝试导入当前SOP
                      importSops([currentRecord]).then((hasDuplicate) => {
                        if (hasDuplicate === false) {
                          // 如果有重复，打开重复对话框
                          setDuplicateDialogOpen(true);
                        }
                      });
                    }}
                    disabled={!currentRecord || loading}
                  >
                    {loading ? '导入中...' : '导入当前SOP'}
                  </Button>
                </div>
              </>
            ) : (
              <div className="flex justify-center items-center h-full text-muted-foreground">
                请从左侧选择一条记录进行预览
              </div>
            )}
          </div>
        </div>
      </SheetContent>
      <Dialog open={duplicateDialogOpen} onOpenChange={setDuplicateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>SOP重复提示</DialogTitle>
            <DialogDescription>
              以下SOP在库中已存在，确认是否在导入时覆盖？
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[300px] overflow-y-auto border rounded-md p-4">
            {duplicateNames.length > 0 ? (
              duplicateNames.map((name, index) => (
                <div key={index} className="py-2 border-b last:border-b-0">
                  {name}
                </div>
              ))
            ) : (
              <div className="text-center py-2 text-muted-foreground">
                未获取到重复SOP名称
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button
              variant="outline"
              onClick={() => {
                const recordsToUse = selectedRecordIds.length > 0
                  ? records.filter(r => selectedRecordIds.includes(r.id))
                  : currentRecord
                    ? [currentRecord]
                    : [];
                importSops(recordsToUse, false, true);
                setDuplicateDialogOpen(false);
              }}
            >
              不覆盖，另存为新SOP
            </Button>
            <Button
              onClick={() => {
                const recordsToUse = selectedRecordIds.length > 0
                  ? records.filter(r => selectedRecordIds.includes(r.id))
                  : currentRecord
                    ? [currentRecord]
                    : [];
                importSops(recordsToUse, true, false);
                setDuplicateDialogOpen(false);
              }}
            >
              覆盖
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Sheet>
  );
}