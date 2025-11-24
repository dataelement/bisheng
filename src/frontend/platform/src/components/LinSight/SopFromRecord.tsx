import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/bs-ui/sheet';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { sopApi } from "@/controllers/API/linsight";
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { TaskFlowContent } from "@/workspace/SopTasks";
import { Check, ChevronDown, ChevronUp, Search, Star } from 'lucide-react';
import * as React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LoadIcon } from '../bs-icons/loading';
import AutoPagination from '../bs-ui/pagination/autoPagination';
import { Tabs, TabsList, TabsTrigger } from '../bs-ui/tabs';
import { Tooltip, TooltipContent, TooltipTrigger } from '../bs-ui/tooltip';
import Tip from '../bs-ui/tooltip/tip';
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

export default function ImportFromRecordsDialog({ open, tools, onOpenChange, setDuplicateNames, duplicateNames, duplicateDialogOpen, setDuplicateDialogOpen, importFormData }) {
  const { toast } = useToast();
  const { t } = useTranslation();
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
  const [linsight, setLinsight] = useState({});
  const [sopShowcase, setSopShowcase] = useState(false);
  const [activeTab, setActiveTab] = useState('manual');
  const [pageInputValue, setPageInputValue] = useState(page.toString());
  const [selectedRecordIds, setSelectedRecordIds] = useState<number[]>([]);
  const [allRecords, setAllRecords] = useState<SopRecord[]>([]);
  const [selectedRecords, setSelectedRecords] = useState<SopRecord[]>([]);
  const [isSavingAsNew, setIsSavingAsNew] = useState(false);
  const [isOverwriting, setIsOverwriting] = useState(false);
  const isMountedRef = useRef(false);
  // Obtain SOP records 
  const fetchRecords = async (isSearch = false) => {
    setLoading(true);
    try {
      const params = {
        keyword: searchTerm,
        // Fix 1: Always pass pagination parameters, regardless of whether a search is performed or not
        page,
        page_size: pageSize,
        sort: sortConfig.direction,
      };

      const res = await sopApi.GetSopRecord(params);

      if (Array.isArray(res)) {
        setAllRecords(res);
        setRecords(res);
        setTotal(res.length);
        if (res.length > 0 && !currentRecord) {
          setCurrentRecord(res[0]);
        }
      } else if (res?.list) {
        setAllRecords(res.list);
        setRecords(res.list);
        setTotal(res.total);
        if (res.list.length > 0 && !currentRecord) {
          setCurrentRecord(res.list[0]);
        }
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) {
      setIsOverwriting(false);
      setIsSavingAsNew(false);
    }
  }, [open]);
  // init
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
  useEffect(() => {
    const timer = setTimeout(() => {
      if (open) {
        setPage(1);  // Reset to the first page when searching 
        fetchRecords(!!searchTerm);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [searchTerm]);
  //  Reload data when search and pagination change 
  useEffect(() => {
    if (open) {
      fetchRecords(!!searchTerm);
    }
  }, [page, pageSize, sortConfig]);

  // sort
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

  // input change
  const handlePageInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    if (value === '' || /^\d+$/.test(value)) {
      setPageInputValue(value);
    }
  };

  // page change
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handlePageInputConfirm();
    }
  };

  // Handle record selection and multi-selection
  const handleSelectRecord = (record: SopRecord) => setCurrentRecord(record);

  const handleToggleSelect = (record: SopRecord, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedRecordIds(prev => {
      const newIds = prev.includes(record.id)
        ? prev.filter(id => id !== record.id)
        : [...prev, record.id];

      // update selectedRecords
      setSelectedRecords(prevRecords =>
        prev.includes(record.id)
          ? prevRecords.filter(r => r.id !== record.id)
          : [...prevRecords, record]
      );

      return newIds;
    });
    setCurrentRecord(record);
  };
  // Select All/Deselect All on Current Page
  const handleToggleSelectAll = () => {
    const currentPageIds = records.map(r => r.id);
    const allSelected = currentPageIds.every(id => selectedRecordIds.includes(id));

    setSelectedRecordIds(prev =>
      allSelected
        ? prev.filter(id => !currentPageIds.includes(id))
        : [...new Set([...prev, ...currentPageIds])]
    );

    // update selectedRecords
    setSelectedRecords(prev => {
      if (allSelected) {
        return prev.filter(r => !currentPageIds.includes(r.id));
      } else {
        const newRecords = records.filter(r => !prev.some(p => p.id === r.id));
        return [...prev, ...newRecords];
      }
    });
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

      toast({ variant: 'success', description: t('importLinsight.success') });
      onOpenChange(false);

      // clear
      setSelectedRecordIds([]);
      setSelectedRecords([]);
    } finally {
      setLoading(false);
    }
  };

  const markdownRef = useRef(null);
  useEffect(() => {
    markdownRef.current?.setValue(currentRecord?.content || '');
  }, [currentRecord])
  useEffect(() => {
    const fetchSopShowcase = async () => {
      const res = await sopApi.getSopShowcaseDetail({ linsight_version_id: currentRecord?.linsight_version_id });
      if (res.execute_tasks.length === 0) {
        setSopShowcase(true);
        setLinsight({});
        return;
      }
      setLinsight({
        ...res.version_info,
        tasks: res.execute_tasks,
        summary: ''
      });
      setSopShowcase(false);
    }
    fetchSopShowcase();
  }, [currentRecord])

  // When switching records, reset the Tab to "guidebook" 
  useEffect(() => {
    if (currentRecord) {
      setActiveTab('manual');
    }
  }, [currentRecord]);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-[87.5vw] min-w-[87.5vw]">
        <div className="flex h-full" onClick={e => e.stopPropagation()}>
          {/* left list */}
          <div className="p-6 w-[50%] min-w-160">
            <SheetHeader>
              <SheetTitle>{t('importLinsight.title')}</SheetTitle>
            </SheetHeader>

            <div className="relative mt-6 mb-6 w-[100%]">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder={t('importLinsight.searchPlaceholder')}
                className="w-full pl-10 pr-4 py-2 rounded-md border focus:outline-none focus:ring-2 focus:ring-primary"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>

            <div className="flex-1 overflow-y-auto h-[calc(100%-180px)]">
              {loading ? (
                <div className="flex justify-center items-center h-full bg-gray-50 rounded-lg">
                  <div className="flex flex-col items-center gap-2">
                    <LoadIcon className="animate-spin w-10 h-10 text-primary" />
                    <span>{t('importLinsight.loading')}</span>
                  </div>
                </div>
              ) : records.length === 0 ? (
                <div className="text-center text-muted-foreground py-4">
                  {searchTerm ? t('importLinsight.noMatchingRecords') : t('importLinsight.noRecords')}
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
                            {t('importLinsight.columns.name')}
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            <div className="flex items-center">
                              {t('importLinsight.columns.createTime')}
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
                            {t('importLinsight.columns.createUser')}
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            {t('importLinsight.columns.rating')}
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
                      <div className="flex items-center whitespace-nowrap min-w-16">
                        <span className="text-sm  text-gray-700">
                          {t('importLinsight.pagination.totalRecords', { total })}
                        </span>
                      </div>
                      <div className="flex items-center ml-4">
                        <AutoPagination
                          page={page}
                          pageSize={pageSize}
                          total={total}
                          onChange={setPage}
                        />
                        <span className="text-sm text-gray-700 mr-2 whitespace-nowrap">
                          {t('importLinsight.pagination.goToPage')}
                        </span>
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
                          {t('importLinsight.pagination.page')}
                        </span>
                        {loading && <LoadIcon className="animate-spin w-4 h-4 ml-2" />}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex items-center justify-start mt-4">
              <span>{t('importLinsight.selectedCount', { selectedCount: selectedRecordIds.length })}</span>
              <Button
                onClick={() => {
                  importSops(selectedRecords, false, false);
                }}
                disabled={selectedRecordIds.length === 0 || loading}
                className="ml-4"
              >
                {loading ? t('importLinsight.loading') : t('importLinsight.batchImport')}
              </Button>
            </div>
          </div>

          {/* right viewpanne */}
          <div className="flex-1 bg-[#fff] p-6 h-full flex flex-col w-[50%]">
            {currentRecord ? (
              <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-col h-full">
                <div className="flex items-center justify-between gap-4">
                  <h3 className="text-lg font-semibold truncate">{currentRecord.name}</h3>
                  <TabsList className='mr-4'>
                    <TabsTrigger value="manual">{t('importLinsight.guidelineManual')}</TabsTrigger>
                    {sopShowcase ? <Tip content={t('importLinsight.noRunningResult')} side="bottom">
                      <span className="inline-block">
                        <TabsTrigger value="result" disabled={sopShowcase}>{t('importLinsight.runningResult')}</TabsTrigger>
                      </span>
                    </Tip> : <TabsTrigger value="result" disabled={sopShowcase}>{t('importLinsight.runningResult')}</TabsTrigger>}
                  </TabsList>
                </div>

                {activeTab === 'manual' && (
                  <div className="flex-1 flex flex-col">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <p className="text-muted-foreground truncate">
                          {currentRecord.description}
                        </p>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="max-w-[300px] break-words">{currentRecord.description}</p>
                      </TooltipContent>
                    </Tooltip>
                    <div className="flex-1 overflow-y-auto bg-gray-50 rounded-md mt-2">
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
                          setSelectedRecordIds([]);
                          setSelectedRecords([]);
                          importSops([currentRecord]).then((hasDuplicate) => {
                            if (hasDuplicate === false) {
                              setDuplicateDialogOpen(true);
                            }
                          });
                        }}
                        disabled={!currentRecord || loading}
                      >
                        {loading ? t('importLinsight.loading') : t('importLinsight.importCurrent')}
                      </Button>
                    </div>
                  </div>
                )}

                {activeTab === 'result' && (
                  <div className="flex-1 flex flex-col">
                    <div className="flex-1 overflow-y-auto bg-gray-50 rounded-md p-4 text-sm text-gray-500">
                      <TaskFlowContent showFeedBack linsight={linsight} />
                    </div>
                    <div className="flex justify-start gap-2 pt-4">
                      <Button
                        onClick={() => {
                          if (!currentRecord) return;
                          setSelectedRecordIds([]);
                          setSelectedRecords([]);
                          importSops([currentRecord]).then((hasDuplicate) => {
                            if (hasDuplicate === false) {
                              setDuplicateDialogOpen(true);
                            }
                          });
                        }}
                        disabled={!currentRecord || loading}
                      >
                        {loading ? t('importLinsight.loading') : t('importLinsight.importCurrent')}
                      </Button>
                    </div>
                  </div>
                )}
              </Tabs>
            ) : (
              <div className="flex justify-center items-center h-full text-muted-foreground">
                {t('importLinsight.preview.noSelection')}
              </div>
            )}
          </div>
        </div>
      </SheetContent>
      <Dialog open={duplicateDialogOpen} onOpenChange={setDuplicateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('importLinsight.duplicateDialog.title')}</DialogTitle>
            <DialogDescription>
              {t('importLinsight.duplicateDialog.description')}
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
                {t('importLinsight.duplicateDialog.noDuplicateNames')}
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button
              variant="outline"
              onClick={async () => {
                setIsSavingAsNew(true);
                if (importFormData) {
                  const newFormData = new FormData();
                  for (const [key, value] of importFormData.entries()) {
                    if (key === 'override' || key === 'save_new') continue;
                    newFormData.append(key, value);
                  }

                  newFormData.append('override', 'false');
                  newFormData.append('save_new', 'true');

                  try {
                    setLoading(true);
                    await captureAndAlertRequestErrorHoc(sopApi.UploadSopRecord(newFormData))
                    toast({ variant: 'success', description: t('importLinsight.success') });
                    setDuplicateDialogOpen(false);
                    onOpenChange(false);
                  } finally {
                    setLoading(false);
                    setIsSavingAsNew(false);
                  }
                } else {
                  const recordsToUse = selectedRecords.length > 0
                    ? selectedRecords
                    : currentRecord
                      ? [currentRecord]
                      : [];
                  importSops(recordsToUse, false, true);
                  setDuplicateDialogOpen(false);
                }
              }}
            >
              {isSavingAsNew ? (
                <div className="flex items-center gap-2">
                  <LoadIcon className="animate-spin w-4 h-4" />
                  {t('importLinsight.duplicateDialog.savingAsNew')}
                </div>
              ) : t('importLinsight.duplicateDialog.saveAsNew')}
            </Button>
            <Button
              onClick={async () => {
                setIsOverwriting(true);
                if (importFormData) {
                  const newFormData = new FormData();
                  for (const [key, value] of importFormData.entries()) {
                    if (key === 'override' || key === 'save_new') continue;
                    newFormData.append(key, value);
                  }
                  newFormData.append('override', 'true');
                  newFormData.append('save_new', 'false');

                  try {
                    setLoading(true);
                    await sopApi.UploadSopRecord(newFormData);
                    toast({ variant: 'success', description: t('importLinsight.success') });
                    setDuplicateDialogOpen(false);
                    onOpenChange(false);
                  } catch (error) {
                    toast({ variant: 'error', description: t('importLinsight.error') });
                    if (isMountedRef.current) {
                      setIsOverwriting(false);
                    }
                  } finally {
                    setLoading(false);
                    if (isMountedRef.current) {
                      setIsOverwriting(false);
                    }
                  }
                } else {
                  const recordsToUse = selectedRecordIds.length > 0
                    ? records.filter(r => selectedRecordIds.includes(r.id))
                    : currentRecord
                      ? [currentRecord]
                      : [];
                  try {
                    await importSops(recordsToUse, true, false);
                    setDuplicateDialogOpen(false);
                  } finally {
                    if (isMountedRef.current) {
                      setIsOverwriting(false);
                    }
                  }
                }
              }}
            >
              {isOverwriting ? (
                <div className="flex items-center gap-2">
                  <LoadIcon className="animate-spin w-4 h-4" />
                  {t('importLinsight.duplicateDialog.overwriting')}
                </div>
              ) : t('importLinsight.duplicateDialog.overwrite')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Sheet>
  );
}