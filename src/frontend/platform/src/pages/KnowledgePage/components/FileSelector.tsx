import { FileIcon } from "@/components/bs-icons/file";
import { truncateString } from "@/util/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@radix-ui/react-dropdown-menu';
import { ChevronDown, ChevronUp, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getMetaFile, readFileByLibDatabase } from '@/controllers/API';
import { LoadingIcon } from "@/components/bs-icons/loading";
import Tip from "@/components/bs-ui/tooltip/tip";

interface FileSelectorProps {
    knowledgeId: string | number;
    selectedFileId: string;
    onFileChange: (fileId: string, fileData: any) => void;
    onWriteableChange: (writeable: boolean) => void;
    disabled?: boolean;
    className?: string;
}

interface FileData {
    id: number | string;
    file_name: string;
    size: number;
    parse_type: string;
    split_rule?: string;
    status?: number;
    object_name?: string;
}

interface FileOption {
    label: string;
    value: string;
    id: string | number;
    name: string;
    size: number;
    type: string;
    filePath: string;
    suffix: string;
    fileType: string;
    fullData: FileData;
}

export default function FileSelector({
    knowledgeId,
    selectedFileId,
    onFileChange,
    onWriteableChange,
    disabled = false,
    className = ''
}: FileSelectorProps) {
    const { t } = useTranslation('knowledge');

    // State
    const [isOpen, setIsOpen] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const [files, setFiles] = useState<FileOption[]>([]);
    const [loading, setLoading] = useState(false);
    const [hasMore, setHasMore] = useState(true);
    const [page, setPage] = useState(1);
    const [error, setError] = useState<string | null>(null);

    // Refs
    const searchInputRef = useRef<HTMLInputElement>(null);
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const loadingRef = useRef(false);
    const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const pageRef = useRef(1); // 使用 ref 存储当前页码，避免闭包问题
    const hasMoreRef = useRef(true); // 使用 ref 存储是否还有更多数据

    const PAGE_SIZE = 100;

    // 加载单个文件数据
    const loadSingleFile = useCallback(async (fileId: string): Promise<FileOption | null> => {
        try {
            const fileData = await getMetaFile(fileId)

            return {
                label: fileData?.file_name || t('file.unnamedFile'),
                value: String(fileData?.id || ''),
                id: fileData?.id || '',
                name: fileData?.file_name || '',
                size: fileData?.file_size || 0,
                type: fileData?.file_name?.split('.').pop() || '',
                filePath: fileData?.object_name || '',
                suffix: fileData?.file_name?.split('.').pop() || '',
                fileType: fileData?.parse_type || 'unknown',
                fullData: fileData || {}
            };
        } catch (err) {
            console.error('Failed to load single file:', err);
            return null;
        }
    }, [knowledgeId, t]);

    // 加载文件列表
    const loadFiles = useCallback(async (pageNum: number, searchQuery: string, isLoadMore: boolean = false) => {
        if (loadingRef.current) return;

        loadingRef.current = true;
        setLoading(true);
        setError(null);

        try {
            const res = await readFileByLibDatabase({
                id: knowledgeId,
                page: pageNum,
                pageSize: PAGE_SIZE,
                name: searchQuery,
                status: 2 // 只加载已解析成功的文件
            });
            if (onWriteableChange) {
                onWriteableChange(res.writeable);
            }
            const filesData = res?.data || [];

            const formattedFiles: FileOption[] = filesData.map((el: FileData) => ({
                label: el?.file_name || t('file.unnamedFile'),
                value: String(el?.id || ''),
                id: el?.id || '',
                name: el?.file_name || '',
                size: el?.size || 0,
                type: el?.file_name?.split('.').pop() || '',
                filePath: el?.object_name || '',
                suffix: el?.file_name?.split('.').pop() || '',
                fileType: el?.parse_type || 'unknown',
                fullData: el || {}
            }));

            if (isLoadMore) {
                setFiles(prev => [...prev, ...formattedFiles]);
            } else {
                setFiles(formattedFiles);
            }

            // 判断是否还有更多数据
            const hasMoreData = filesData.length === PAGE_SIZE;
            setHasMore(hasMoreData);
            hasMoreRef.current = hasMoreData; // 同步更新 ref

            // 返回加载的文件列表，用于后续判断
            return formattedFiles;
        } catch (err) {
            console.error('Failed to load files:', err);
            setError(t('file.loadFailed'));
            return [];
        } finally {
            setLoading(false);
            loadingRef.current = false;
        }
    }, [knowledgeId, t]);

    // 初始加载
    useEffect(() => {
        if (!knowledgeId) return;

        const initLoad = async () => {
            setPage(1);
            pageRef.current = 1; // 初始化 ref
            hasMoreRef.current = true; // 重置 hasMore

            // 加载第一页
            const firstPageFiles = await loadFiles(1, '', false);

            // 如果有选中的文件ID，检查是否在第一页中
            if (firstPageFiles) {
                let selectedFile = firstPageFiles.find(f => String(f.value) === String(selectedFileId));

                if (!selectedFile) {
                    console.log('Selected file not in first page, loading it separately:', selectedFileId);
                    // 单独加载选中的文件
                    selectedFile = await loadSingleFile(selectedFileId);

                    if (selectedFile) {
                        // 将选中的文件添加到列表第一个位置
                        setFiles(prev => {
                            return [selectedFile, ...prev]
                        });
                        console.log('Added selected file to the top of list');
                    }
                }
                onFileChange(String(selectedFile.value), selectedFile.fullData);
            }

        };

        selectedFileId && initLoad();
    }, [loadFiles, loadSingleFile]);

    // 搜索处理（防抖）
    const firstRef = useRef(true);
    useEffect(() => {
        if (firstRef.current) {
            firstRef.current = false;
            return;
        }
        if (searchTimeoutRef.current) {
            clearTimeout(searchTimeoutRef.current);
        }

        searchTimeoutRef.current = setTimeout(() => {
            setPage(1);
            pageRef.current = 1; // 同步更新 ref
            hasMoreRef.current = true; // 重置 hasMore
            loadFiles(1, searchTerm, false);
        }, 300);

        return () => {
            if (searchTimeoutRef.current) {
                clearTimeout(searchTimeoutRef.current);
            }
        };
    }, [searchTerm, loadFiles]);

    // 加载更多（滚动到底部）
    const loadMoreFiles = useCallback(() => {
        if (loadingRef.current || !hasMoreRef.current) {
            console.log('Skip loading: loading=', loadingRef.current, 'hasMore=', hasMoreRef.current);
            return;
        }

        const nextPage = pageRef.current + 1;
        pageRef.current = nextPage; // 先更新 ref
        setPage(nextPage); // 再更新 state

        console.log('Loading page:', nextPage);
        loadFiles(nextPage, searchTerm, true);
    }, [searchTerm, loadFiles]);

    // 设置滚动监听 - 使用滚动事件替代 Intersection Observer（更可靠）
    useEffect(() => {
        if (!isOpen) return;

        // 延迟执行以确保 Portal 已经渲染完成
        const timer = setTimeout(() => {
            const scrollContainer = scrollContainerRef.current;
            if (!scrollContainer) {
                console.warn('Scroll container not found');
                return;
            }

            // 使用滚动事件监听
            const handleScroll = () => {
                const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
                // 当滚动到距离底部 50px 时加载更多
                if (scrollHeight - scrollTop - clientHeight < 50) {
                    console.log('Scroll triggered, hasMore:', hasMoreRef.current, 'loading:', loadingRef.current);
                    if (hasMoreRef.current && !loadingRef.current) {
                        loadMoreFiles();
                    }
                }
            };

            scrollContainer.addEventListener('scroll', handleScroll);

            // 清理函数
            return () => {
                scrollContainer.removeEventListener('scroll', handleScroll);
            };
        }, 100); // 延迟 100ms 确保 Portal 渲染完成

        return () => {
            clearTimeout(timer);
        };
    }, [isOpen, hasMore, loading, loadMoreFiles]);

    // 下拉框打开时聚焦搜索框
    useEffect(() => {
        if (isOpen && searchInputRef.current) {
            setTimeout(() => {
                searchInputRef.current?.focus();
            }, 100);
        }
    }, [isOpen]);

    // 处理文件选择
    const handleSelectFile = useCallback((file: FileOption) => {
        if (String(file.value) === String(selectedFileId)) {
            setIsOpen(false);
            return;
        }

        onFileChange(String(file.value), file.fullData);
        setSearchTerm('');
        setIsOpen(false);
    }, [selectedFileId, onFileChange]);

    // 获取当前选中的文件
    const selectedFile = useMemo(() => {
        return files.find(f => String(f.value) === String(selectedFileId));
    }, [files, selectedFileId]);

    // 获取文件类型
    const getFileType = useCallback((fileName: string) => {
        const parts = fileName.split('.');
        return parts.length > 1 ? parts.pop()!.toLowerCase() : 'txt';
    }, []);

    return (
        <div className={`relative ${className}`}>
            <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
                <DropdownMenuTrigger asChild disabled={disabled}>
                    <div className={`
                        flex items-center gap-2 max-w-[480px] px-3 py-2 rounded-md cursor-pointer
                        hover:bg-gray-100 transition-colors
                        ${isOpen ? 'ring-1 ring-gray-300' : ''}
                        ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
                    `}>
                        {selectedFile ? (
                            <>
                                <FileIcon
                                    type={getFileType(selectedFile.label)}
                                    className="size-[30px] min-w-[30px]"
                                />
                                <Tip content={selectedFile.label}>
                                    <div className="truncate flex-1">{selectedFile.label}</div>
                                </Tip>
                            </>
                        ) : (
                            <span className="text-gray-500">{t('file.selectFile')}</span>
                        )}
                        {isOpen ? (
                            <ChevronUp className="ml-2 h-4 w-4 opacity-50" />
                        ) : (
                            <ChevronDown className="ml-2 h-4 w-4 opacity-50" />
                        )}
                    </div>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                    className="w-[480px] border border-gray-200 bg-white shadow-lg rounded-md p-0 z-[100]"
                    align="start"
                    sideOffset={5}
                    onCloseAutoFocus={(e) => e.preventDefault()}
                >
                    {/* 搜索框 */}
                    <div className="p-2 border-b border-gray-200 sticky top-0 bg-white z-10">
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-blue-500" />
                            <input
                                ref={searchInputRef}
                                type="text"
                                placeholder={t('file.searchFiles')}
                                className="w-full pl-9 pr-3 py-2 text-sm bg-white rounded-md outline-none ring-1 ring-gray-200 focus:ring-2 focus:ring-blue-500"
                                value={searchTerm}
                                onChange={(e) => {
                                    e.stopPropagation();
                                    setSearchTerm(e.target.value);
                                }}
                                onKeyDown={(e) => {
                                    e.stopPropagation();
                                    if (e.key === 'Escape') {
                                        setIsOpen(false);
                                    }
                                }}
                                onClick={(e) => {
                                    e.stopPropagation();
                                }}
                            />
                        </div>
                    </div>

                    {/* 文件列表 */}
                    <div
                        ref={scrollContainerRef}
                        className="max-h-[400px] overflow-y-auto"
                    >
                        {error ? (
                            <div className="px-4 py-8 text-center text-red-500 text-sm">
                                {error}
                            </div>
                        ) : files.length === 0 && !loading ? (
                            <div className="px-4 py-8 text-center text-gray-500 text-sm">
                                {searchTerm ? t('file.noSearchResults') : t('file.noFiles')}
                            </div>
                        ) : (
                            <>
                                {files.map((file) => (
                                    <DropdownMenuItem
                                        key={file.id}
                                        onSelect={(e) => {
                                            e.preventDefault();
                                            handleSelectFile(file);
                                        }}
                                        className="cursor-pointer hover:bg-gray-50 px-3 py-2 focus:bg-gray-50 outline-none"
                                    >
                                        <Tip content={file.label} side="top" styleClasses="z-[999]">
                                            <div className="flex items-center gap-3 w-full h-full">
                                                <FileIcon
                                                    type={getFileType(file.label)}
                                                    className="size-[30px] min-w-[30px] text-current"
                                                />
                                                <span className="flex-1 min-w-0 truncate text-sm">
                                                    {truncateString(file.label, 50)}
                                                </span>
                                                {String(file.value) === String(selectedFileId) && (
                                                    <div className="w-4 h-4 bg-blue-500 rounded-full flex items-center justify-center flex-shrink-0">
                                                        <div className="w-2 h-2 bg-white rounded-full"></div>
                                                    </div>
                                                )}
                                            </div>
                                        </Tip>
                                    </DropdownMenuItem>
                                ))}

                                {/* 加载更多指示器 */}
                                {hasMore && (
                                    <div className="px-4 py-3 flex justify-center items-center min-h-10">
                                        {loading && <LoadingIcon className="w-5 h-5" />}
                                    </div>
                                )}

                                {/* 没有更多数据提示 */}
                                {!hasMore && files.length > 0 && (
                                    <div className="px-4 py-2 text-center text-xs text-gray-400">
                                        {t('file.noMoreFiles')}
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </DropdownMenuContent>
            </DropdownMenu>

            {error && (
                <p className="absolute text-sm text-red-500 mt-1">{error}</p>
            )}
        </div>
    );
}
