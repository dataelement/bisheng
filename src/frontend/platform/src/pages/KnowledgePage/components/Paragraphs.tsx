import { FileIcon } from "@/components/bs-icons/file";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader } from '@/components/bs-ui/dialog';
import { SearchInput } from '@/components/bs-ui/input';
import AutoPagination from '@/components/bs-ui/pagination/autoPagination';
import ShadTooltip from "@/components/ShadTooltipComponent";
import { delChunkApi, getFileBboxApi, getFilePathApi, getKnowledgeChunkApi, getKnowledgeDetailApi, readFileByLibDatabase, updateChunkApi, addMetadata, saveUserMetadataApi,getMetaFile } from '@/controllers/API';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useTable } from '@/util/hook';
import { truncateString } from "@/util/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@radix-ui/react-dropdown-menu';
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { AlertCircle, ArrowLeft, Calendar as CalendarIcon, ChevronDown, ChevronUp, ClipboardPenLine, Clock3, Edit2, FileText, Hash, Plus, Search, Trash2, Type, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import useKnowledgeStore from '../useKnowledgeStore';
import ParagraphEdit from './ParagraphEdit';
import PreviewFile from './PreviewFile';
import PreviewParagraph from './PreviewParagraph';
import Tip from "@/components/bs-ui/tooltip/tip";
import { cname } from "@/components/bs-ui/utils";
import React from "react";
import { Calendar } from "@/components/bs-ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { format } from "date-fns";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";

// 类型图标常量
const TYPE_ICONS = {
    String: <Type />,
    Number: <Hash />,
    Time: <Clock3 />
};

// 元数据行组件
const MetadataRow = React.memo(({isKnowledgeAdmin, item, onDelete, onValueChange, isSmallScreen, t, showInput = true }) => {
    // 将日期字符串转换为 Date 对象
    const getDateValue = (dateString) => {
        if (!dateString) return null;
        try {
            return new Date(dateString);
        } catch {
            return null;
        }
    };

    const handleInputChange = (e) => {
        onValueChange(item.id, e.target.value);
    };

    const handleNumberChange = (e) => {
        const value = e.target.value;
        // 只允许数字
        if (value === '' || /^-?\d*\.?\d*$/.test(value)) {
            onValueChange(item.id, value);
        }
    };

    const handleDateChange = (date) => {
        // 将日期对象转换为字符串格式
        const dateString = date ? format(date, 'yyyy-MM-dd') : '';
        onValueChange(item.id, dateString);
    };

    return (
        <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-lg">
            {/* 类型图标 */}
            <span className={isSmallScreen ? "text-base" : "text-lg"}>
                {TYPE_ICONS[item.type]}
            </span>

            {/* 类型标签 */}
            <span className={cname(
                "text-gray-500 min-w-[60px]",
                isSmallScreen ? "text-xs" : "text-sm"
            )}>
                {item.type}
            </span>

            {/* 变量名 */}
            <span className={cname(
                "font-medium truncate flex-1 min-w-0",
                isSmallScreen ? "text-sm" : ""
            )}>
                {item.name}
            </span>

            {/* 输入框 - 根据类型显示不同的输入组件 */}
            {showInput && (
                <div className="flex-1 min-w-0">
                    {item.type === 'String' && (
                        <input
                            disabled={!isKnowledgeAdmin}
                            type="text"
                            value={item.value || ''}
                            onChange={handleInputChange}
                            placeholder={t('请输入文本')}
                            className={cname(
                                "w-full px-3 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                                isSmallScreen ? "py-1 text-xs h-7" : "py-1.5 text-sm h-8"
                            )}
                        />
                    )}

                    {item.type === 'Number' && (
                        <input
                             disabled={!isKnowledgeAdmin}
                            type="number"
                            value={item.value || ''}
                            onChange={handleNumberChange}
                            placeholder={t('请输入数字')}
                            className={cname(
                                "w-full px-3 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                                isSmallScreen ? "py-1 text-xs h-7" : "py-1.5 text-sm h-8"
                            )}
                        />
                    )}

                    {item.type === 'Time' && (
                        <DatePicker
                        isKnowledgeAdmin={isKnowledgeAdmin}
                            value={item.value}
                            placeholder={t('选择日期时间')}
                            showTime={true}
                            onChange={(selectedDate) => {
                                const formattedValue = selectedDate
                                    ? format(selectedDate, 'yyyy-MM-dd HH:mm:ss')
                                    : '';
                                onValueChange(item.id, formattedValue);
                            }}
                        />
                    )}
                </div>
            )}

            {/* 删除按钮 */}
            <button
                onClick={() => onDelete(item.id)}
                disabled={!isKnowledgeAdmin}
                className="p-1 hover:bg-gray-200 rounded transition-colors flex-shrink-0"
                title={t('删除')}
            >
                <Trash2 size={isSmallScreen ? 14 : 16} className="text-gray-500" />
            </button>
        </div>
    );
});

MetadataRow.displayName = 'MetadataRow';

export default function Paragraphs({ fileId, onBack }) {
    console.log('Props fileId:', fileId);

    const { t } = useTranslation('knowledge');
    const { id } = useParams();
    const navigate = useNavigate();
    const { isEditable, selectedBbox } = useKnowledgeStore();
    const [hasInited, setHasInited] = useState(false);
    const location = useLocation();
    const [chunkSwitchTrigger, setChunkSwitchTrigger] = useState(0);
    const [selectedFileId, setSelectedFileId] = useState('');
    const [currentFile, setCurrentFile] = useState(null);
    const [fileUrl, setFileUrl] = useState('');
    const [chunks, setChunks] = useState([]);
    const [rawFiles, setRawFiles] = useState([]);
    const [isKnowledgeAdmin, setIsKnowledgeAdmin] = useState(false); // 是否为知识库管理员（有管理权限）
    const [metadataDialog, setMetadataDialog] = useState({
        open: false,
        file: null
    });
    const [paragraph, setParagraph] = useState({
        fileId: '',
        chunkId: '',
        parseType: '',
        isUns: false,
        show: false
    });
    const [selectError, setSelectError] = useState(null);
    const [isFetchingUrl, setIsFetchingUrl] = useState(false);
    const [partitions, setPartitions] = useState()
    const isLoadingFilesRef = useRef(false);
    const isMountedRef = useRef(true);
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const searchInputRef = useRef(null);
    const isChangingRef = useRef(false);
    const [isInitReady, setIsInitReady] = useState(false);
    const [previewUrl, setPreviewUrl] = useState()
    const [hasChunkBboxes, setHasChunkBboxes] = useState(false);
    const latestFileUrlRef = useRef('');
    const latestPreviewUrlRef = useRef('');
    const latestOriginalUrlRef = useRef('');
    const selectedChunkIndex = useKnowledgeStore((state) => state.selectedChunkIndex);

    // 元数据相关状态
    const [newMetadata, setNewMetadata] = useState({
        name: '',
        type: 'String' as 'String' | 'Number' | 'Time',
    });
    const [metadataError, setMetadataError] = useState('');
    // 统一管理右侧弹窗状态
    const [sideDialog, setSideDialog] = useState<{
        type: 'search' | 'create' | null;
        open: boolean;
    }>({
        type: null,
        open: false
    });
    // 主元数据弹窗中的元数据列表
    const [mainMetadataList, setMainMetadataList] = useState([]);

    const setSelectedBbox = useKnowledgeStore((state) => state.setSelectedBbox);

    // 右侧弹窗相关状态与ref
    const mainMetadataDialogRef = useRef<HTMLDivElement>(null);
    const [sideDialogPosition, setSideDialogPosition] = useState({ top: 0, left: 0 });
    const [screenWidth, setScreenWidth] = useState(window.innerWidth);
    const isSmallScreen = screenWidth < 1366;
    const sideDialogWidth = isSmallScreen ? 240 : 300;

    const [predefinedMetadata, setPredefinedMetadata] = useState([
    ]);

    useEffect(() => {
        setSelectedBbox([])
    }, [selectedChunkIndex])

    const tableConfig = useMemo(() => ({
        file_ids: selectedFileId ? [selectedFileId] : [],
        knowledge_id: id
    }), [selectedFileId]);

    const {
        page,
        pageSize,
        data: datalist,
        total,
        loading,
        setPage,
        search,
        reload,
        filterData,
        refreshData
    } = useTable(tableConfig,
        async (param) => {
            const response = await getKnowledgeChunkApi({
                ...param,
                limit: param.pageSize,
                knowledge_id: id
            });

            let chunkBboxes = [];
            try {
                const firstChunk = response.data?.[0];
                if (firstChunk?.metadata?.bbox) {
                    if (typeof firstChunk.metadata.bbox === 'string' && JSON.parse(firstChunk?.metadata?.bbox).chunk_bboxes === '') {
                        console.log('bbox为空字符串');
                        chunkBboxes = [];
                    } else {
                        const bboxObj = JSON.parse(firstChunk.metadata.bbox);
                        chunkBboxes = bboxObj.chunk_bboxes || [];
                    }
                }
            } catch (e) {
                console.error('解析 chunk_bboxes 失败:', e);
                chunkBboxes = [];
            }

            const isBboxesNotEmpty = Array.isArray(chunkBboxes) && chunkBboxes.length > 0;
            setHasChunkBboxes(isBboxesNotEmpty);
            console.log('chunk_bboxes 是否非空:', isBboxesNotEmpty, '原始数据:', chunkBboxes);

            return response;
        }
    );

    const [load, setLoad] = useState(true);
    const fetchFileUrl = useCallback(async (fileId) => {
        console.log('获取文件URL:', fileId);
        if (!fileId) return '';

        try {
            setIsFetchingUrl(true);
            const res = await getFilePathApi(fileId);
            const pares = await getFileBboxApi(fileId);
            setPartitions(pares || []);

            const currentFile = rawFiles.find(f => String(f.id) === String(fileId));
            let finalUrl = '';
            let finalPreviewUrl = '';

            const hasPreviewUrl = typeof res.preview_url === 'string' && res.preview_url.trim() !== '';
            const hasOriginalUrl = typeof res.original_url === 'string' && res.original_url.trim() !== '';

            if (currentFile) {
                const isUnsOrLocal = currentFile.parse_type === "uns" || currentFile.parse_type === "local";

                if (isUnsOrLocal) {
                    const isBboxesEmpty = !hasChunkBboxes;
                    if (!isBboxesEmpty && hasPreviewUrl) {
                        finalUrl = res.preview_url.trim();
                        finalPreviewUrl = res.preview_url.trim();
                    } else {
                        finalUrl = hasOriginalUrl ? res.original_url.trim() : '';
                        finalPreviewUrl = finalUrl;
                    }
                } else {
                    if (hasPreviewUrl) {
                        finalUrl = res.preview_url.trim();
                        finalPreviewUrl = res.preview_url.trim();
                    } else {
                        finalUrl = hasOriginalUrl ? res.original_url.trim() : '';
                        finalPreviewUrl = finalUrl;
                    }
                }
            } else {
                finalUrl = hasPreviewUrl ? res.preview_url.trim() : (hasOriginalUrl ? res.original_url.trim() : '');
                finalPreviewUrl = finalUrl;
            }

            if (finalUrl) {
                finalUrl = decodeURIComponent(finalUrl);
                finalPreviewUrl = decodeURIComponent(finalPreviewUrl);
                setFileUrl(finalUrl);
                setPreviewUrl(finalPreviewUrl);
                latestOriginalUrlRef.current = hasOriginalUrl ? decodeURIComponent(res.original_url.trim()) : '';
                return finalUrl;
            } else {
                setFileUrl('');
                setPreviewUrl('');
                latestOriginalUrlRef.current = '';
                return '';
            }
        } catch (err) {
            console.error('获取文件URL失败:', err);
            setFileUrl('');
            setPreviewUrl('');
            setPartitions([]);
            latestOriginalUrlRef.current = '';
            return '';
        } finally {
            setIsFetchingUrl(false);
        }
    }, [rawFiles, hasChunkBboxes]);

    useEffect(() => {
        if (location.pathname.startsWith('/filelib/adjust/') && !window.history.state?.isAdjustMode) {
            const adjustId = location.pathname.split('/')[3];
            if (adjustId) {
                navigate(`/filelib/${adjustId}`, { replace: true });
            }
        }
    }, [location.pathname, navigate]);

    useEffect(() => {
        if (!selectedFileId || !datalist.length) {
            setChunks([]);
            return;
        }

        const generatedChunks = datalist.map((item, index) => ({
            ...item,
            text: item.text || '',
            bbox: item.metadata?.bbox || {},
            activeLabels: {},
            chunkIndex: item.metadata?.chunk_index,
            page: item.metadata?.page || 0,
            metadata: item.metadata || {}
        }));

        setChunks(generatedChunks);
    }, [datalist, selectedFileId]);

    const handleFileChange = useCallback(async (newFileId) => {
        console.log('文件切换触发:', newFileId, '当前选中:', selectedFileId);

        newFileId = String(newFileId);
        const currentId = String(selectedFileId);

        if (newFileId === currentId || !newFileId || rawFiles.length === 0) {
            setIsDropdownOpen(false);
            return;
        }

        const selectedFile = rawFiles.find(f => String(f.id) === newFileId);
        if (selectedFile) {
            console.log(selectedFile, fileUrl, previewUrl, 888);

            setCurrentFile({
                label: selectedFile.file_name || '',
                value: newFileId,
                id: selectedFile.id || '',
                name: selectedFile.file_name || '',
                size: selectedFile.size || 0,
                type: selectedFile.file_name?.split('.').pop() || '',
                filePath: fileUrl || previewUrl,
                suffix: selectedFile.file_name?.split('.').pop() || '',
                fileType: selectedFile.parse_type || 'unknown',
                fullData: selectedFile || {}
            });
            setSelectedFileId(newFileId);
        }

        isChangingRef.current = true;
        setSelectError(null);
        setIsFetchingUrl(true);
        setChunks([]);
        setIsDropdownOpen(false);
        setFileUrl('');
        setPreviewUrl('');
        latestOriginalUrlRef.current = '';

        try {
            if (!selectedFile) throw new Error('未找到选中的文件');

            if (filterData) filterData({ file_ids: [newFileId] });
            await fetchFileUrl(newFileId);
            await reload();
            setChunkSwitchTrigger(prev => prev + 1);
        } catch (err) {
            console.error('文件切换失败:', err);
            setSelectError(err.message || '文件切换失败');
        } finally {
            setIsFetchingUrl(false);
            isChangingRef.current = false;
            setLoad(false);
        }
    }, [rawFiles, fetchFileUrl, filterData, reload, selectedFileId]);

    useEffect(() => {
        const loadFiles = async () => {
            if (isLoadingFilesRef.current || !isMountedRef.current) return;
            isLoadingFilesRef.current = true;

            try {
                const res = await readFileByLibDatabase({
                    id,
                    page: 1,
                    pageSize: 4000,
                    status: 2
                });
                setIsKnowledgeAdmin(false)
                const filesData = res?.data || [];
                setRawFiles(filesData);
                console.log('加载文件列表:', filesData);

                setIsInitReady(true);
                setHasInited(true);
            } catch (err) {
                console.error('加载文件失败:', err);
                setSelectError('加载文件列表失败');
                setIsInitReady(true);
                setHasInited(true);
            } finally {
                isLoadingFilesRef.current = false;
            }
        };

        loadFiles();
        return () => { isMountedRef.current = false; };
    }, [id]);

    useEffect(() => {
        if (rawFiles.length === 0 || !isInitReady || !isMountedRef.current || !hasInited) return;

        if (!selectedFileId) {
            const targetFileId = fileId ? String(fileId) : String(rawFiles[0]?.id || '');
            console.log('目标文件ID（rawFiles就绪后）:', targetFileId);

            if (targetFileId) {
                handleFileChange(targetFileId);
            }
        }
    }, [rawFiles, isInitReady, fileId, handleFileChange, selectedFileId, hasInited]);

    // 元数据相关处理函数
    const handleDeleteMainMetadata = useCallback((id) => {
        setMainMetadataList(prev => prev.filter(item => item.id !== id));
    }, []);

    const handleMainMetadataValueChange = useCallback((id, value) => {
        setMainMetadataList(prev => prev.map(item =>
            item.id === id ? { ...item, value } : item
        ));
    }, []);

    const handleSaveNewMetadata = useCallback(async () => {
        const name = newMetadata.name.trim();
        const type = newMetadata.type;

        // 验证规则
        if (!name) {
            setMetadataError(t('名称不能为空。'));
            return;
        }

        if (name.length > 255) {
            setMetadataError(t('名称不能超过255个字符。'));
            return;
        }

        // 格式验证：必须以小写字母开头，且只能包含小写字母、数字和下划线
        const nameRegex = /^[a-z][a-z0-9_]*$/;
        if (!nameRegex.test(name)) {
            setMetadataError(t('必须以小写字母开头，且只能包含小写字母、数字和下划线。'));
            return;
        }

        // 检查是否已存在同名元数据
        const exists = predefinedMetadata.some(item => item.name === name);
        if (exists) {
            setMetadataError(t('元数据名已存在。'));
            return;
        }

        try {
            await addMetadata(Number(id), [{
                field_name: name,
                field_type: type.toLowerCase()
            }]);

            // 3. 保存成功后，更新本地状态
            const newItem = {
                id: `meta_${Date.now()}`,
                name: name,
                type: type,
            };

            setPredefinedMetadata(prev => [...prev, newItem]);

            closeSideDialog();
        } catch (error) {
            console.error("创建元数据字段失败:", error);
            setMetadataError(t('创建失败，请稍后重试。'));
        }
    }, [newMetadata, predefinedMetadata, t]);

    const handleSearchMetadataClick = useCallback(async () => {
        try {
            const knowledgeDetails = await getKnowledgeDetailApi([id]);
            const knowledgeDetail = knowledgeDetails[0];

            if (knowledgeDetail && Array.isArray(knowledgeDetail.metadata_fields)) {
                const formattedFields = knowledgeDetail.metadata_fields.map(field => ({
                    id: `meta_${field.field_name}`,
                    name: field.field_name,
                    type: field.field_type.charAt(0).toUpperCase() + field.field_type.slice(1),
                }));
                setPredefinedMetadata(formattedFields);
            } else {
                setPredefinedMetadata([]);
            }
        } catch (error) {
            console.error("获取知识库元数据字段失败:", error);
            setPredefinedMetadata([]);
        } finally {
            setMetadataError('');
            setSideDialog({ type: 'search', open: true });
            setSearchTerm("");
        }
    }, [id, t]);

    const handleCreateMetadataClick = useCallback(() => {
        setNewMetadata({ name: '', type: 'String' });
        setMetadataError('');
        setSideDialog({ type: 'create', open: true });
    }, []);

    // 关闭右侧弹窗
    const closeSideDialog = useCallback(() => {
        setSideDialog({ type: null, open: false });
        setMetadataError('');
        setSearchTerm("");
        setNewMetadata({ name: '', type: 'String' });
    }, []);

    // 从搜索弹窗添加元数据到主列表
    const handleAddFromSearch = useCallback((metadata) => {
        const exists = mainMetadataList.some(item => item.name === metadata.name);
        if (exists) {
            toast({ description: '该元数据已存在，不能重复添加。' });
            return;
        }
        const newItem = {
            ...metadata,
            id: `meta_${Date.now()}_${metadata.name}`,
            value: ''
        };
        setMainMetadataList(prev => [...prev, newItem]);
        closeSideDialog();
    }, [closeSideDialog]);

    const filteredPredefinedMetadata = useMemo(() => {
        return predefinedMetadata.filter(meta =>
            meta.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
            (meta.description && meta.description.toLowerCase().includes(searchTerm.toLowerCase()))
        );
    }, [predefinedMetadata, searchTerm]);

    const handleChunkChange = useCallback((chunkIndex, text) => {
        let chunkIndexPage = chunkIndex % pageSize;
        console.log('转换后的localIndex:', chunkIndexPage);

        const bbox = { chunk_bboxes: selectedBbox };

        const targetChunk = chunks.find(chunk => chunk.chunkIndex === chunkIndex);
        const bboxStr = selectedBbox.length ? JSON.stringify(bbox.length ? JSON.stringify(bbox) : targetChunk?.bbox) :
            captureAndAlertRequestErrorHoc(updateChunkApi({
                knowledge_id: Number(id),
                file_id: selectedFileId || currentFile?.id || '',
                chunk_index: chunkIndex,
                text,
                bbox: bboxStr
            }));

        setChunks(chunks => chunks.map(chunk =>
            chunk.chunkIndex === chunkIndex ? { ...chunk, bbox: bboxStr, text } : chunk
        ));

        refreshData(
            (item) => item?.metadata?.chunk_index === chunkIndex,
            (item) => ({ text, metadata: { ...item.metadata, bbox: bboxStr } })
        );
    }, [id, currentFile, refreshData, selectedBbox, chunks]);

    const files = useMemo(() => {
        return (rawFiles || []).map(el => ({
            label: el?.file_name || '未命名文件',
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
    }, [rawFiles]);

    const safeChunks = useMemo(() => {
        if (!selectedFileId || !datalist.length) return [];
        return (datalist || []).map((item, index) => ({
            text: item?.text || '',
            title: `分段${index + 1}`,
            chunkIndex: item?.metadata?.chunk_index || index,
            bbox: item?.metadata?.bbox
        }));
    }, [datalist, selectedFileId, chunkSwitchTrigger]);

  const handleMetadataClick = useCallback(async () => {
    if (currentFile?.fullData) {
        try {
            const res = await getMetaFile(currentFile.id);
            const fetchedMetadata = res.user_metadata || [];
            const sortedMetadata = fetchedMetadata.sort((a, b) => {
                return a.updated_at - b.updated_at;
            });

            // 3. 格式化排序后的元数据
            const formattedMetadata = sortedMetadata.map(meta => {
                let type = 'String';
                if (!isNaN(Number(meta.field_value))) {
                    type = 'Number';
                } else if (!isNaN(Date.parse(meta.field_value))) {
                    type = 'Time';
                }

                return {
                    id: `meta_${meta.field_name}`,
                    name: meta.field_name,
                    type: type,
                    value: meta.field_value,
                };
            });

            // 4. 更新状态
            setMainMetadataList(formattedMetadata);

            // 5. 打开弹窗
            setMetadataDialog({
                open: true,
                file: currentFile.fullData
            });
        } catch (error) {
            console.error("获取文件元数据失败:", error);
            setMetadataDialog({
                open: true,
                file: currentFile.fullData
            });
        }
    }
}, [currentFile]);

    const handleAdjustSegmentation = useCallback(() => {
        const currentFileUrl = latestOriginalUrlRef.current;
        const currentPreviewUrl = latestPreviewUrlRef.current;

        navigate(`/filelib/adjust/${id}`, {
            state: {
                skipToStep: 2,
                fileId: selectedFileId,
                fileData: {
                    previewUrl: currentPreviewUrl,
                    id: currentFile?.id,
                    name: currentFile?.name,
                    split_rule: currentFile?.split_rule || currentFile?.fullData?.split_rule,
                    status: currentFile?.status,
                    filePath: currentFileUrl || currentPreviewUrl,
                    suffix: currentFile?.suffix,
                    fileType: currentFile?.fileType,
                },
                isAdjustMode: true
            }
        });
    }, [id, selectedFileId, currentFile, navigate]);

    const splitRuleDesc = useCallback((file) => {
        if (!file.split_rule) return '';
        const suffix = file.file_name?.split('.').pop()?.toUpperCase() || '';
        try {
            const rule = JSON.parse(file.split_rule);
            const { excel_rule } = rule;

            if (excel_rule && ['XLSX', 'XLS', 'CSV'].includes(suffix)) {
                return `每 ${excel_rule.slice_length} 行作为一个分段`;
            }

            const { separator, separator_rule } = rule;
            if (separator && separator_rule && separator.length === separator_rule.length) {
                const displayItems = separator.map((sep, index) => {
                    const displaySep = sep
                        .replace(/\n/g, '\\n')
                        .replace(/\r/g, '\\r')
                        .replace(/\t/g, '\\t');

                    const prefix = separator_rule[index] === 'before' ? '✂️' : '';
                    const suffix = separator_rule[index] === 'after' ? '✂️' : '';

                    return `${prefix}${displaySep}${suffix}`;
                });
                return displayItems.join(', ');
            }
        } catch (e) {
            console.error('解析切分策略失败:', e);
        }

        return file.split_rule
            .replace(/\n/g, '\\n')
            .replace(/\r/g, '\\r')
            .replace(/\t/g, '\\t');
    }, []);

    const handleDeleteChunk = useCallback((data) => {
        const updatedChunks = chunks.filter(chunk => chunk.chunkIndex !== data);
        setChunks(updatedChunks);

        if (selectedChunkIndex === data) {
            setSelectedBbox([]);
        }

        captureAndAlertRequestErrorHoc(delChunkApi({
            knowledge_id: Number(id),
            file_id: selectedFileId || currentFile?.id || '',
            chunk_index: data || 0
        }));

        reload();

    }, [
        id,
        reload,
        chunks,
        selectedFileId,
        currentFile?.id,
        setChunks,
        selectedChunkIndex,
        setSelectedBbox
    ]);

    const formatFileSize = useCallback((bytes) => {
        if (bytes === 0) return '0 Bytes';

        const KB = 1024;
        const MB = KB * 1024;
        const GB = MB * 1024;

        if (bytes < MB) {
            return `${(bytes / KB).toFixed(2)} KB`;
        } else if (bytes < GB) {
            return `${(bytes / MB).toFixed(2)} MB`;
        } else {
            return `${(bytes / GB).toFixed(2)} GB`;
        }
    }, []);

    const filteredFiles = files.filter(file =>
        file.label.toLowerCase().includes(searchTerm.toLowerCase())
    );

    const previewRules = useMemo(() => ({
        fileList: currentFile ? [{
            id: currentFile.id,
            filePath: fileUrl,
            fileName: currentFile.name,
            suffix: currentFile.suffix,
            fileType: currentFile.fileType,
            excelRule: {} // 根据实际需要添加 excel 规则
        }] : [],
        pageHeaderFooter: false, // 页面页眉页脚处理
        chunkOverlap: 200, // 块重叠大小
        chunkSize: 1000, // 块大小
        enableFormula: false, // 是否启用公式
        forceOcr: false, // 是否强制 OCR
        knowledgeId: id, // 知识库ID
        retainImages: false, // 是否保留图片
        separator: [], // 分隔符
        separatorRule: [] // 分隔规则
    }), [currentFile, id]);

    const isExcelFile = currentFile && ['xlsx', 'xls', 'csv'].includes(currentFile.suffix?.toLowerCase());
    const isPreviewVisible =
        isInitReady &&
        !isExcelFile &&
        selectedFileId &&
        currentFile &&
        (previewUrl || fileUrl) &&
        !isFetchingUrl;
    const isParagraphVisible = datalist.length > 0;

    const contentLayoutClass = useMemo(() => {
        const isSingleVisible = isPreviewVisible !== isParagraphVisible;
        if (isSingleVisible) {
            return "flex justify-center bg-background-main min-h-0";
        }
        return "flex bg-background-main min-h-0";
    }, [isPreviewVisible, isParagraphVisible, isExcelFile]);

    useEffect(() => {
        latestFileUrlRef.current = fileUrl;
        latestPreviewUrlRef.current = previewUrl;
    }, [fileUrl, previewUrl]);

    // 右侧弹窗位置计算 - 优化版本
    const updateSideDialogPosition = useCallback(() => {
        if (mainMetadataDialogRef.current && sideDialog.open) {
            const rect = mainMetadataDialogRef.current.getBoundingClientRect();
            const gap = isSmallScreen ? 8 : 16;
            let left = rect.right + gap;

            // 避免右侧弹窗超出屏幕
            if (left + sideDialogWidth > screenWidth) {
                left = screenWidth - sideDialogWidth - 8;
            }

            setSideDialogPosition({
                top: Math.max(rect.top, 8), // 确保不会超出顶部
                left: Math.max(left, 8) // 确保不会超出左侧
            });
        }
    }, [mainMetadataDialogRef, sideDialog.open, isSmallScreen, screenWidth, sideDialogWidth]);

    // 窗口 resize 监听和位置更新
    useEffect(() => {
        const handleResize = () => {
            const newWidth = window.innerWidth;
            setScreenWidth(newWidth);
        };

        window.addEventListener("resize", handleResize);
        return () => window.removeEventListener("resize", handleResize);
    }, []);

    // 当主弹窗或侧边弹窗状态变化时更新位置
    useEffect(() => {
        if (metadataDialog.open && sideDialog.open) {
            // 使用 setTimeout 确保 DOM 已经更新
            const timer = setTimeout(() => {
                updateSideDialogPosition();
            }, 50);
            return () => clearTimeout(timer);
        }
    }, [metadataDialog.open, sideDialog.open, updateSideDialogPosition]);
// 保存用户元数据到后端
const handleSaveUserMetadata = useCallback(async () => {
  // 1. 表单验证：检查是否有必填项为空
  const invalidItems = mainMetadataList.filter(item => !item.value?.trim());
  if (invalidItems.length > 0) {
    const invalidNames = invalidItems.map(item => item.name).join('、');
    setMetadataError(t(`元数据「${invalidNames}」的值不能为空，请完善后再保存`));
    return;
  }

  const knowledge_id = selectedFileId
  const user_metadata_list = mainMetadataList.map(item => ({
      field_name: item.name,
      field_value: item.value
    }))
  try {
    // 3. 调用API保存数据
    await saveUserMetadataApi(knowledge_id,user_metadata_list);
    
    // 4. 保存成功处理
    toast({
      title: t('成功'),
      description: t('元数据已成功保存'),
    });
    setMetadataDialog(prev => ({ ...prev, open: false })); // 关闭弹窗
    setMetadataError(''); // 清除错误提示
  } catch (error) {
    // 5. 保存失败处理
    console.error('保存元数据失败：', error);
    setMetadataError(t('保存失败，请检查网络或联系管理员'));
  }
}, [mainMetadataList, id, t]);
    // 右侧弹窗公共容器组件
    const SideDialogContent = useMemo(() =>
        React.forwardRef<
            React.ElementRef<typeof DialogPrimitive.Content>,
            React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
        >(({ children, className, ...props }, ref) => (
            <DialogPrimitive.Portal>
                <DialogPrimitive.Content
                    ref={ref}
                    {...props}
                    className={cname(
                        "fixed z-50 flex flex-col border bg-background dark:bg-[#303134] shadow-lg duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 sm:rounded-lg",
                        `w-[${sideDialogWidth}px]`,
                        isSmallScreen ? "p-3 text-sm" : "p-5",
                        className
                    )}
                    style={{
                        top: `${sideDialogPosition.top}px`,
                        left: `${sideDialogPosition.left}px`,
                        transform: "none",
                        maxHeight: "80vh",
                    }}
                >
                    {children}
                </DialogPrimitive.Content>
            </DialogPrimitive.Portal>
        ))
        , [sideDialogWidth, isSmallScreen, sideDialogPosition, closeSideDialog]);
    SideDialogContent.displayName = "SideDialogContent";

    if (load) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="relative flex flex-col h-[calc(100vh-64px)]">
            {/* 顶部导航栏 */}
            <div className="flex justify-between items-center px-4 pt-4 pb-4">
                <div className="min-w-72 max-w-[440px] flex items-center gap-2">
                    <ShadTooltip content={t('back')} side="top">
                        <button
                            className="extra-side-bar-buttons w-[36px] max-h-[36px]"
                            onClick={onBack}
                        >
                            <ArrowLeft className="side-bar-button-size" />
                        </button>
                    </ShadTooltip>
                    <div className="relative">
                        <DropdownMenu onOpenChange={setIsDropdownOpen}>
                            <DropdownMenuTrigger asChild>
                                <div className={`
                    flex items-center gap-2 max-w-[480px] px-3 py-2 rounded-md cursor-pointer
                    hover:bg-gray-100 ${isDropdownOpen ? 'ring-1 ring-gray-300' : ''}
                `}>
                                    {selectedFileId ? (
                                        <>
                                            <FileIcon
                                                type={(() => {
                                                    const targetFile = files.find(f => f.value === selectedFileId);
                                                    if (!targetFile) return 'txt';
                                                    const parts = targetFile.label.split('.');
                                                    return parts.length > 1 ? parts.pop().toLowerCase() : 'txt';
                                                })()}
                                                className="size-[30px] min-w-[30px]"
                                            />
                                            <div className="truncate">{files.find(f => f.value === selectedFileId)?.label || ''}</div>
                                        </>
                                    ) : (
                                        <span>{t('selectFile')}</span>
                                    )}
                                    {isDropdownOpen ? (
                                        <ChevronUp className="ml-2 h-4 w-4 opacity-50" />
                                    ) : (
                                        <ChevronDown className="ml-2 h-4 w-4 opacity-50" />
                                    )}
                                </div>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                className="w-[300px] border border-gray-200 bg-white shadow-md p-0 z-[100]"
                                align="start"
                                sideOffset={5}
                                style={{ zIndex: 9999 }}
                                onCloseAutoFocus={(e) => e.preventDefault()}
                            >
                                <div className="p-2 border-b border-gray-200">
                                    <div className="relative">
                                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-blue-500" />
                                        <input
                                            ref={searchInputRef}
                                            type="text"
                                            placeholder={t('搜索文件')}
                                            className="w-full pl-9 pr-3 py-2 text-sm bg-white rounded-md outline-none ring-1 ring-gray-200"
                                            value={searchTerm}
                                            onChange={(e) => {
                                                e.stopPropagation();
                                                setSearchTerm(e.target.value);
                                            }}
                                            onKeyDown={(e) => {
                                                e.stopPropagation();
                                                if (e.key === 'Escape') {
                                                    setIsDropdownOpen(false);
                                                }
                                            }}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                            }}
                                        />
                                    </div>
                                </div>
                                <div className="max-h-[300px] overflow-y-auto">
                                    {filteredFiles.map((file) => (
                                        <DropdownMenuItem
                                            key={file.value}
                                            onSelect={(e) => {
                                                e.preventDefault();
                                                handleFileChange(file.value);
                                                setSearchTerm("");
                                                setIsDropdownOpen(false);
                                            }}
                                            className="cursor-pointer hover:bg-gray-50 px-3 py-2 relative"
                                        >
                                            <div className="flex items-center gap-3 w-full h-full">
                                                <FileIcon
                                                    type={(() => {
                                                        const parts = file.label.split('.');
                                                        return parts.length > 1 ? parts.pop().toLowerCase() : 'txt';
                                                    })()}
                                                    className="size-[30px] min-w-[30px] text-current"
                                                />
                                                <span className="flex-1 min-w-0 truncate">
                                                    {truncateString(file.label, 35)}
                                                </span>
                                                {file.value === selectedFileId && (
                                                    <div className="w-4 h-4 bg-blue-500 rounded-full flex items-center justify-center">
                                                        <div className="w-2 h-2 bg-white rounded-full"></div>
                                                    </div>
                                                )}
                                            </div>
                                        </DropdownMenuItem>
                                    ))}
                                </div>
                            </DropdownMenuContent>
                        </DropdownMenu>
                        {selectError && (
                            <p className="absolute text-sm text-red-500 mt-1">{selectError}</p>
                        )}
                    </div>
                </div>

                <div className="flex items-center gap-2 ml-auto">
                    <div className="w-60">
                        <SearchInput
                            placeholder={t('searchSegments')}
                            onChange={(e) => search(e.target.value)}
                            disabled={!selectedFileId}
                        />
                    </div>
                    <Button variant="outline" onClick={handleMetadataClick} className="px-4 whitespace-nowrap">
                        <ClipboardPenLine size={16} strokeWidth={1.5} className="mr-1"/>
                        {t('元数据')}
                    </Button>
                    <Tip content={!isEditable && '暂无操作权限'} side='top'>
                        <Button
                            disabled={!isEditable}
                            onClick={handleAdjustSegmentation}
                            className={`px-4 whitespace-nowrap disabled:pointer-events-auto`}>
                            {t('调整分段策略')}
                        </Button>
                    </Tip>
                </div>
            </div>

            {/* 主要内容区 */}
            <div className={contentLayoutClass}>
                {isPreviewVisible ? (
                    <PreviewFile
                        rawFiles={rawFiles}
                        key={selectedFileId}
                        partitions={partitions}
                        previewUrl={previewUrl}
                        urlState={{ load: !isFetchingUrl, url: previewUrl || fileUrl }}
                        file={currentFile}
                        chunks={safeChunks}
                        setChunks={setChunks}
                        rules={previewRules}
                        edit
                    />
                ) : (
                    !isParagraphVisible && (
                        <div className="flex justify-center items-center h-[400px] text-gray-500 bg-gray-50 rounded-lg w-full max-w-4xl">
                            <FileIcon className="size-8 mb-3 opacity-50" />
                            <p className="text-lg font-medium">{t('文件无法预览')}</p>
                        </div>
                    )
                )}

                {isParagraphVisible ? (
                    <div className={isPreviewVisible ? "w-1/2" : " w-full max-w-3xl"}>
                        <div className="flex justify-center items-center relative text-sm gap-2 p-2 pt-0 ">
                            <PreviewParagraph
                                key={`preview-${selectedFileId}-${chunkSwitchTrigger}`}
                                fileId={selectedFileId}
                                previewCount={datalist.length}
                                edit={isEditable}
                                className="h-[calc(100vh-206px)] pb-6"
                                fileSuffix={currentFile?.suffix || ''}
                                loading={loading}
                                chunks={safeChunks}
                                onDel={handleDeleteChunk}
                                onChange={handleChunkChange}
                            />
                        </div>
                    </div>
                ) : (
                    !isPreviewVisible && (
                        <div className="flex justify-center items-center flex-col h-[400px] text-gray-500 bg-gray-50 rounded-lg w-full max-w-4xl">
                            <FileText className="size-8 mb-3 opacity-50" />
                            <p className="text-lg font-medium">{t('无分段数据')}</p>
                        </div>
                    )
                )}
            </div>

            {/* 分页 */}
            <div className="bisheng-table-footer px-6">
                <AutoPagination
                    className="justify-end"
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={setPage}
                    disabled={!selectedFileId}
                />
            </div>

            {/* 主元数据弹窗 - 添加ref用于位置计算 */}
            <Dialog open={metadataDialog.open} onOpenChange={(open) => setMetadataDialog(prev => ({ ...prev, open }))}>
                <DialogContent
                    ref={mainMetadataDialogRef}
                    className="sm:max-w-[525px] max-w-[625px] max-h-[80vh] overflow-y-auto"
                >
                    <DialogHeader>
                        <h3 className="text-lg font-semibold">{t('元数据')}</h3>
                    </DialogHeader>
                    <button
                        onClick={handleSearchMetadataClick}
                        className="py-2 w-full flex items-center justify-center gap-2 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                        <Plus size={16} />
                        <span>{t('添加元数据')}</span>
                    </button>

                    {/* 主元数据列表 */}
                    {mainMetadataList.length > 0 && (
                        <div className="space-y-2 mt-4">
                            {mainMetadataList.map((metadata) => (
                                <MetadataRow
                                    isKnowledgeAdmin={isKnowledgeAdmin}
                                    key={metadata.id}
                                    item={metadata}
                                    onDelete={handleDeleteMainMetadata}
                                    onValueChange={handleMainMetadataValueChange}
                                    isSmallScreen={isSmallScreen}
                                    t={t}
                                    showInput={true}
                                />
                            ))}
                        </div>
                    )}

                    <div className="grid gap-4 py-4">
                        <div className="font-medium">文档信息</div>
                        <div className="space-y-2">
                            {[
                                {
                                    label: t('文件id'),
                                    value: metadataDialog.file?.file_name,
                                },
                                {
                                    label: t('文件名称'),
                                    value: metadataDialog.file?.file_name,
                                    isFileName: true
                                },
                                {
                                    label: t('创建时间'),
                                    value: metadataDialog.file?.create_time ? metadataDialog.file.create_time.replace('T', ' ') : null
                                },
                                {
                                    label: t('创建者'),
                                    value: metadataDialog.file?.file_name,
                                },
                                {
                                    label: t('更新者'),
                                    value: metadataDialog.file?.file_name,
                                },
                                {
                                    label: t('更新时间'),
                                    value: metadataDialog.file?.update_time ? metadataDialog.file.update_time.replace('T', ' ') : null
                                },
                                { label: t('原始文件大小'), value: metadataDialog.file?.file_size ? formatFileSize(metadataDialog.file.file_size) : null },
                                {
                                    label: t('切分策略'),
                                    value: metadataDialog.file ? splitRuleDesc(metadataDialog.file) : null
                                },
                                { label: t('全文摘要'), value: metadataDialog.file?.title }
                            ].map((item, index) => (
                                item.value && (
                                    <div key={index} className="grid grid-cols-4 gap-4 items-center">
                                        <span className="text-sm text-muted-foreground col-span-1">{item.label}</span>
                                        <span className={`col-span-3 text-sm ${item.isFileName ? 'truncate max-w-full' : ''}`}>
                                            {item.value || t('none')}
                                        </span>
                                    </div>
                                )
                            ))}
                        </div>
                    </div>
                    <div className="flex justify-end gap-2 pt-4 border-t border-gray-200">
                        {/* 取消按钮 */}
                        <Button
                            variant="outline"
                            onClick={() => setMetadataDialog(prev => ({ ...prev, open: false }))}
                            className={cname(isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm")}
                        >
                            {t('取消')}
                        </Button>
                        {/* 保存按钮 */}
                        <Button
                            onClick={handleSaveUserMetadata}
                            className={cname(
                                "bg-blue-500 hover:bg-blue-600",
                                isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm"
                            )}
                        >
                            {t('保存')}
                        </Button>
                    </div>
                </DialogContent>
            </Dialog>

            {/* 分段编辑弹窗 */}
            <Dialog open={paragraph.show} onOpenChange={(show) => setParagraph(prev => ({ ...prev, show }))}>
                <DialogContent close={false} className='size-full max-w-full sm:rounded-none p-0 border-none'>
                    <ParagraphEdit
                        edit={isEditable}
                        fileId={paragraph.fileId}
                        chunkId={paragraph.chunkId}
                        isUns={paragraph.isUns || ['etl4lm', 'un_etl4lm'].includes(paragraph.parseType)}
                        parseType={paragraph.parseType}
                        onClose={() => setParagraph(prev => ({ ...prev, show: false }))}
                        onChange={(value) => refreshData(
                            (item) => item?.metadata?.chunk_index === paragraph.chunkId,
                            { text: value }
                        )}
                    />
                </DialogContent>
            </Dialog>

            {/* 统一的右侧弹窗 */}
            <DialogPrimitive.Dialog open={sideDialog.open} onOpenChange={(open) => {
                if (!open) closeSideDialog();
            }}>
                <SideDialogContent>
                    {sideDialog.type === 'search' && (
                        <>
                            <DialogHeader>
                                <div className="relative w-full">
                                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-blue-500" />
                                    <input
                                        ref={searchInputRef}
                                        type="text"
                                        placeholder={t('搜索元数据')}
                                        className={cname(
                                            "w-full pl-9 pr-3 py-2 text-sm bg-white rounded-md outline-none ring-1 ring-gray-200",
                                            isSmallScreen ? "text-xs py-1.5" : ""
                                        )}
                                        value={searchTerm}
                                        onChange={(e) => {
                                            e.stopPropagation();
                                            setSearchTerm(e.target.value);
                                        }}
                                        onKeyDown={(e) => {
                                            e.stopPropagation();
                                            if (e.key === 'Escape') {
                                                closeSideDialog();
                                            }
                                        }}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                        }}
                                    />
                                </div>
                            </DialogHeader>

                            {/* 可滚动区域 - 使用 flex 布局 */}
                            <div className="flex-1 min-h-0 overflow-y-auto">
                                <div
                                    className="h-full overflow-y-auto"
                                    onWheel={(e) => {
                                        // 手动处理滚动事件，确保正常工作
                                        e.stopPropagation();
                                    }}
                                >
                                    <div className="space-y-3 pr-2">
                                        {filteredPredefinedMetadata.map((metadata) => (
                                            <div
                                                key={metadata.id}
                                                className="flex items-center justify-between p-3 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer"
                                                onClick={() => handleAddFromSearch(metadata)}
                                            >
                                                <div className="flex items-center gap-3 flex-1">
                                                    <span className={isSmallScreen ? "text-base" : "text-lg"}>
                                                        {TYPE_ICONS[metadata.type]}
                                                    </span>
                                                    <span className={cname(
                                                        "text-gray-500 min-w-[60px]",
                                                        isSmallScreen ? "text-xs" : "text-sm"
                                                    )}>
                                                        {metadata.type}
                                                    </span>
                                                    <div className="flex-1 min-w-0">
                                                        <div className="font-medium text-sm">{metadata.name}</div>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="grid gap-4 pt-4 border-t">
                                <div className="space-y-2">
                                    <button
                                        onClick={handleCreateMetadataClick}
                                        disabled={!isKnowledgeAdmin}
                                        className="py-2 w-full flex items-center justify-center gap-2 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                                    >
                                        <Plus size={isSmallScreen ? 14 : 16} />
                                        <span>{t('新建元数据')}</span>
                                    </button>
                                </div>
                            </div>
                        </>
                    )}

                    {sideDialog.type === 'create' && (
                        <>
                            <DialogHeader>
                                <h3 className={cname("text-lg font-semibold", isSmallScreen ? "text-base" : "")}>{t('新建元数据')}</h3>
                                <DialogDescription className={isSmallScreen ? "text-xs" : ""}>请输入新元数据的名称和类型。</DialogDescription>
                            </DialogHeader>

                            <div className="grid gap-4 py-4">
                                {/* 元数据类型 */}
                                <div className="space-y-1.5">
                                    <label className={cname("block font-medium", isSmallScreen ? "text-xs" : "")}>{t('类型')}</label>
                                    <div className="flex gap-1">
                                        {['String', 'Number', 'Time'].map((type) => (
                                            <button
                                                key={type}
                                                onClick={() => setNewMetadata(prev => ({ ...prev, type: type as 'String' | 'Number' | 'Time' }))}
                                                className={cname(
                                                    "flex-1 rounded-md font-medium transition-colors",
                                                    newMetadata.type === type
                                                        ? "bg-blue-500 text-white"
                                                        : "bg-gray-100 hover:bg-gray-200 text-gray-700",
                                                    isSmallScreen ? "py-1.5 px-2 text-xs" : "py-2 px-4 text-sm"
                                                )}
                                            >
                                                {type}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                {/* 元数据名称 */}
                                <div className="space-y-1.5">
                                    <label className={cname("block font-medium", isSmallScreen ? "text-xs" : "")}>{t('名称')}</label>
                                    <input
                                        type="text"
                                        value={newMetadata.name}
                                        onChange={(e) => {
                                            setNewMetadata(prev => ({ ...prev, name: e.target.value }));
                                            // 清除错误状态当用户开始输入时
                                            if (metadataError) setMetadataError('');
                                        }}
                                        placeholder={t('请输入元数据名称')}
                                        className={cname(
                                            "w-full px-3 py-2 border rounded-md text-sm",
                                            isSmallScreen ? "text-xs h-8 py-1.5" : "",
                                            // 添加错误状态样式
                                            metadataError ? "border-red-500 focus:ring-red-500" : "border-gray-300 focus:ring-blue-500"
                                        )}
                                    />
                                </div>

                                {/* 错误提示 */}
                                {metadataError && (
                                    <div className={cname(
                                        "flex items-center gap-1.5 text-red-500",
                                        isSmallScreen ? "text-xs" : "text-sm"
                                    )}>
                                        <AlertCircle size={isSmallScreen ? 14 : 16} />
                                        <span>{metadataError}</span>
                                    </div>
                                )}
                            </div>

                            <div className="flex justify-end gap-2">
                                <Button
                                    variant="outline"
                                    onClick={() => setSideDialog({ type: 'search', open: true })}
                                    className={cname(isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm")}
                                >
                                    {t('取消')}
                                </Button>
                                <Button
                                    onClick={handleSaveNewMetadata}
                                    className={cname(
                                        "bg-blue-500 hover:bg-blue-600",
                                        isSmallScreen ? "px-3 py-1 text-xs" : "px-4 py-2 text-sm"
                                    )}
                                >
                                    {t('保存')}
                                </Button>
                            </div>
                        </>
                    )}
                </SideDialogContent>
            </DialogPrimitive.Dialog>
        </div>
    );
}