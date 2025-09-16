import { FileIcon } from "@/components/bs-icons/file";
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogHeader } from '@/components/bs-ui/dialog';
import { SearchInput } from '@/components/bs-ui/input';
import AutoPagination from '@/components/bs-ui/pagination/autoPagination';
import ShadTooltip from "@/components/ShadTooltipComponent";
import { delChunkApi, getFileBboxApi, getFilePathApi, getKnowledgeChunkApi, readFileByLibDatabase, updateChunkApi } from '@/controllers/API';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useTable } from '@/util/hook';
import { truncateString } from "@/util/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@radix-ui/react-dropdown-menu';
import { ArrowLeft, ChevronDown, ChevronUp, FileText, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import useKnowledgeStore from '../useKnowledgeStore';
import ParagraphEdit from './ParagraphEdit';
import PreviewFile from './PreviewFile';
import PreviewParagraph from './PreviewParagraph';


export default function Paragraphs({ fileId, onBack }) {
    console.log('Props fileId:', fileId);

    const { t } = useTranslation('knowledge');
    const { id } = useParams();
    const navigate = useNavigate();
    const { isEditable, selectedBbox } = useKnowledgeStore();
    const [hasInited, setHasInited] = useState(false);
    const location = useLocation();
    const [chunkSwitchTrigger, setChunkSwitchTrigger] = useState(0);
    // 状态管理（完全保留原始定义）
    const [selectedFileId, setSelectedFileId] = useState('');
    const [currentFile, setCurrentFile] = useState(null);
    const [fileUrl, setFileUrl] = useState('');
    const [chunks, setChunks] = useState([]);
    const [rawFiles, setRawFiles] = useState([]);
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
    // 引用（完全保留原始定义）
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

    const [selectedChunkIndex, setSelectedBbox] = useKnowledgeStore((state) => [state.selectedChunkIndex, state.setSelectedBbox]);
    useEffect(() => {
        // 切换chunk清空选中的高亮标注bbox
        setSelectedBbox([])
    }, [selectedChunkIndex])

    // 表格配置（完全保留原始逻辑）
    const tableConfig = useMemo(() => ({
        file_ids: selectedFileId ? [selectedFileId] : []
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

            // 修复：解析 chunk_bboxes 并存储“是否非空”的布尔值
            let chunkBboxes = [];
            try {
                const firstChunk = response.data?.[0];
                if (firstChunk?.metadata?.bbox) {
                    console.log(JSON.parse(firstChunk?.metadata?.bbox).chunk_bboxes, 6666666666666);

                    // 先判断bbox是否为空字符串
                    if (typeof firstChunk.metadata.bbox === 'string' && JSON.parse(firstChunk?.metadata?.bbox).chunk_bboxes === '') {
                        console.log('bbox为空字符串');
                        chunkBboxes = [];
                    } else {
                        // 解析JSON
                        const bboxObj = JSON.parse(firstChunk.metadata.bbox);
                        chunkBboxes = bboxObj.chunk_bboxes || [];
                    }
                }
            } catch (e) {
                console.error('解析 chunk_bboxes 失败:', e);
                chunkBboxes = [];
            }

            // 存储“是否非空数组”的布尔值（而非原始数组）
            const isBboxesNotEmpty = Array.isArray(chunkBboxes) && chunkBboxes.length > 0;
            setHasChunkBboxes(isBboxesNotEmpty);
            console.log('chunk_bboxes 是否非空:', isBboxesNotEmpty, '原始数据:', chunkBboxes);

            return response;
        }
    );
    const fetchFileUrl = useCallback(async (fileId) => {
        console.log('获取文件URL:', fileId);
        if (!fileId) return '';

        try {
            setIsFetchingUrl(true);
            const res = await getFilePathApi(fileId);
            const pares = await getFileBboxApi(fileId);
            setPartitions(pares || []);

            // 获取当前选中的文件信息
            const currentFile = rawFiles.find(f => String(f.id) === String(fileId));
            let finalUrl = '';
            let finalPreviewUrl = '';

            // 检查是否有有效的preview_url和original_url
            const hasPreviewUrl = typeof res.preview_url === 'string' && res.preview_url.trim() !== '';
            const hasOriginalUrl = typeof res.original_url === 'string' && res.original_url.trim() !== '';

            if (currentFile) {
                console.log(currentFile, 3);

                // 判断是否为UNS或LOCAL类型
                const isUnsOrLocal = currentFile.parse_type === "uns" || currentFile.parse_type === "local";
                console.log(isUnsOrLocal, currentFile, 4444444);


                if (isUnsOrLocal) {
                    // UNS或LOCAL类型：根据bbox是否有效选择URL
                    const isBboxesValid = hasChunkBboxes;
                    const isBboxesEmpty = !hasChunkBboxes || chunkBboxes.length === 0;
                    if (!isBboxesEmpty && hasPreviewUrl) {
                        // 有有效bbox且有preview_url → 使用preview_url
                        console.log(1111);

                        finalUrl = res.preview_url.trim();
                        finalPreviewUrl = res.preview_url.trim();
                        console.log('UNS/LOCAL类型（有有效bbox）：使用preview_url');
                    } else {
                        // 无有效bbox（为空数组/字符串）或无preview_url → 强制使用original_url
                        console.log(2222);

                        finalUrl = hasOriginalUrl ? res.original_url.trim() : '';
                        finalPreviewUrl = finalUrl;
                        console.log('UNS/LOCAL类型（无有效bbox或无preview_url）：使用original_url');
                    }
                } else {
                    // 其他类型：优先使用preview_url，无则使用original_url
                    if (hasPreviewUrl) {
                        // 有preview_url → 优先使用
                        finalUrl = res.preview_url.trim();
                        finalPreviewUrl = res.preview_url.trim();
                        console.log('其他类型：使用preview_url');
                    } else {
                        // 无preview_url → 使用original_url或备选URL
                        finalUrl = hasOriginalUrl ? res.original_url.trim() : '';
                        finalPreviewUrl = finalUrl;
                        console.log('其他类型（无preview_url）：使用original_url');
                    }
                }
            } else {
                // 如果没有找到当前文件，使用默认策略
                finalUrl = hasPreviewUrl ? res.preview_url.trim() : (hasOriginalUrl ? res.original_url.trim() : '');
                finalPreviewUrl = finalUrl;
                console.log('未找到文件信息，使用默认URL策略');
            }

            if (finalUrl) {
                finalUrl = decodeURIComponent(finalUrl);
                finalPreviewUrl = decodeURIComponent(finalPreviewUrl);
                // 同时更新状态和ref（ref会同步生效）
                setFileUrl(finalUrl);
                setPreviewUrl(finalPreviewUrl);
                return finalUrl;
            } else {
                setFileUrl('');
                setPreviewUrl('');
                return '';
            }
        } catch (err) {
            console.error('获取文件URL失败:', err);
            setFileUrl('');
            setPreviewUrl('');
            setPartitions([]);
            return '';
        } finally {
            setIsFetchingUrl(false);
        }
    }, [rawFiles, hasChunkBboxes]);





    useEffect(() => {
        // 检查当前路径是否是adjust页面且没有有效的state数据
        if (location.pathname.startsWith('/filelib/adjust/') && !window.history.state?.isAdjustMode) {
            // 提取ID（如从/filelib/adjust/2066中提取2066）
            const adjustId = location.pathname.split('/')[3];
            if (adjustId) {
                // 重定向到对应的filelib页面
                navigate(`/filelib/${adjustId}`, { replace: true });
            }
        }
    }, [location.pathname, navigate]);
    // 从datalist生成chunks（完全保留原始逻辑）
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
            chunkIndex: item.metadata?.chunk_index || index,
            page: item.metadata?.page || 0,
            metadata: item.metadata || {}
        }));

        setChunks(generatedChunks);
    }, [datalist, selectedFileId]);

    const handleFileChange = useCallback(async (newFileId) => {
        console.log('文件切换触发:', newFileId, '当前选中:', selectedFileId);

        // 强制类型转换，避免类型不匹配
        newFileId = String(newFileId);
        const currentId = String(selectedFileId);

        if (newFileId === currentId || !newFileId || rawFiles.length === 0) {
            setIsDropdownOpen(false);
            return;
        }

        // 立即更新UI，避免闪烁
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

                const filesData = res?.data || [];
                setRawFiles(filesData);
                console.log('加载文件列表:', filesData);

                setIsInitReady(true);
                setHasInited(true); // 标记为已初始化
            } catch (err) {
                console.error('加载文件失败:', err);
                setSelectError('加载文件列表失败');
                setIsInitReady(true);
                setHasInited(true); // 即使失败也标记为已初始化
            } finally {
                isLoadingFilesRef.current = false;
            }
        };

        loadFiles();
        return () => { isMountedRef.current = false; };
    }, [id]);


    useEffect(() => {
        // 核心修复：增加hasInited判断，防止切换后重复初始化
        if (rawFiles.length === 0 || !isInitReady || !isMountedRef.current || !hasInited) return;

        // 只有在首次加载时执行自动选中，切换后不执行
        if (!selectedFileId) {
            const targetFileId = fileId ? String(fileId) : String(rawFiles[0]?.id || '');
            console.log('目标文件ID（rawFiles就绪后）:', targetFileId);

            if (targetFileId) {
                handleFileChange(targetFileId);
            }
        }
    }, [rawFiles, isInitReady, fileId, handleFileChange, selectedFileId, hasInited]);

    // 处理分段修改（完全保留原始逻辑）
    const handleChunkChange = useCallback((chunkIndex, text) => {
        const bbox = { chunk_bboxes: selectedBbox };
        // selectedBbox空数组时，使用safeChunks的bbox
        const bboxStr = selectedBbox.length ? JSON.stringify(bbox) : safeChunks[chunkIndex].bbox;

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
    }, [id, currentFile, refreshData, selectedBbox]);

    // 格式化文件列表（完全保留原始逻辑）
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

    // 生成安全的chunks数据（完全保留原始逻辑）
    const safeChunks = useMemo(() => {
        if (!selectedFileId || !datalist.length) return [];
        return (datalist || []).map((item, index) => ({
            text: item?.text || '',
            title: `分段${index + 1}`,
            chunkIndex: item?.metadata?.chunk_index || index,
            bbox: item?.metadata?.bbox
        }));
    }, [datalist, selectedFileId, chunkSwitchTrigger]);

    // 打开元数据弹窗（完全保留原始逻辑）
    const handleMetadataClick = useCallback(() => {
        if (currentFile?.fullData) {
            setMetadataDialog({
                open: true,
                file: currentFile.fullData
            });
        }
    }, [currentFile]);

    // 调整分段策略（完全保留原始逻辑）
    const handleAdjustSegmentation = useCallback(() => {
        console.log(currentFile, fileUrl, previewUrl, 789);
        const currentFileUrl = latestFileUrlRef.current;
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

    // 解析切分策略描述（完全保留原始逻辑）
    const splitRuleDesc = useCallback((file) => {
        if (!file.split_rule) return '';
        const suffix = file.file_name?.split('.').pop()?.toUpperCase() || '';
        try {
            const rule = JSON.parse(file.split_rule);
            const { excel_rule } = rule;

            // 处理Excel文件规则
            if (excel_rule && ['XLSX', 'XLS', 'CSV'].includes(suffix)) {
                return `每 ${excel_rule.slice_length} 行作为一个分段`;
            }

            // 处理分隔符规则
            const { separator, separator_rule } = rule;
            if (separator && separator_rule && separator.length === separator_rule.length) {
                const displayItems = separator.map((sep, index) => {
                    // 核心修复：将实际换行符转换为可见的 \n 字符串
                    const displaySep = sep
                        .replace(/\n/g, '\\n')  // 替换换行符
                        .replace(/\r/g, '\\r')  // 替换回车符（可选）
                        .replace(/\t/g, '\\t'); // 替换制表符（可选）

                    // 根据规则添加切割符号
                    const prefix = separator_rule[index] === 'before' ? '✂️' : '';
                    const suffix = separator_rule[index] === 'after' ? '✂️' : '';

                    return `${prefix}${displaySep}${suffix}`;
                });
                return displayItems.join(', ');
            }
        } catch (e) {
            console.error('解析切分策略失败:', e);
        }

        // 解析失败时的兜底处理
        return file.split_rule
            .replace(/\n/g, '\\n')
            .replace(/\r/g, '\\r')
            .replace(/\t/g, '\\t');
    }, []);


    // 删除分段（完全保留原始逻辑）
    const handleDeleteChunk = useCallback((data) => {
        captureAndAlertRequestErrorHoc(delChunkApi({
            knowledge_id: Number(id),
            file_id: selectedFileId || currentFile?.id || '',
            chunk_index: data || 0
        }));
        reload();
    }, [id, reload]);

    // 格式化文件大小（完全保留原始逻辑）
    const formatFileSize = useCallback((bytes) => {
        if (bytes === 0) return '0 Bytes';

        // 定义单位转换边界（1024进制）
        const KB = 1024;
        const MB = KB * 1024;
        const GB = MB * 1024;

        // 根据文件大小选择合适的单位
        if (bytes < MB) {
            // 小于1024KB（1MB），使用KB
            return `${(bytes / KB).toFixed(2)} KB`;
        } else if (bytes < GB) {
            // 1024KB至1024MB之间，使用MB
            return `${(bytes / MB).toFixed(2)} MB`;
        } else {
            // 1024MB及以上，使用GB
            return `${(bytes / GB).toFixed(2)} GB`;
        }
    }, []);
    // 筛选下拉框文件（完全保留原始逻辑）
    const filteredFiles = files.filter(file =>
        file.label.toLowerCase().includes(searchTerm.toLowerCase())
    );

    // 预览组件规则配置（完全保留原始逻辑）
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

    // 预览显示判断（完全保留原始逻辑）
    const isExcelFile = currentFile && ['xlsx', 'xls', 'csv'].includes(currentFile.suffix?.toLowerCase());
    const isPreviewVisible =
        isInitReady && // 新增：确保组件初始化完成，避免异步数据未加载
        !isExcelFile &&
        selectedFileId &&
        currentFile &&
        (previewUrl || fileUrl) && // 兼容 previewUrl 或 fileUrl 任一有值
        !isFetchingUrl;
    const isParagraphVisible = datalist.length > 0;

    // 布局类名计算（完全保留原始逻辑）
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
    // 渲染部分（完全保留原始样式，无任何修改）
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
                                                    if (!targetFile) return 'txt'; // 文件不存在时默认'txt'
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
                                onCloseAutoFocus={(e) => e.preventDefault()} // 阻止自动失焦
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
                                                // 核心修复3：同步执行，去掉setTimeout，避免首次进入时异步阻塞
                                                handleFileChange(file.value);
                                                setSearchTerm("");
                                                setIsDropdownOpen(false); // 强制关闭菜单
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
                        {t('元数据')}
                    </Button>
                    <Button onClick={handleAdjustSegmentation} className="px-4 whitespace-nowrap">
                        {t('调整分段策略')}
                    </Button>
                </div>
            </div>

            {/* 主要内容区 */}
            <div className={contentLayoutClass}>
                {/* 预览组件 - 修复显示问题 */}
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

                {/* 分段组件 */}
                {isParagraphVisible ? (
                    <div className={isPreviewVisible ? "w-1/2" : " w-full max-w-3xl"}>
                        <div className="flex justify-center items-center relative text-sm gap-2 p-2 pt-0 ">
                            <PreviewParagraph
                                key={`preview-${selectedFileId}-${chunkSwitchTrigger}`}
                                fileId={selectedFileId}
                                previewCount={datalist.length}
                                edit={isEditable}
                                className="h-[calc(100vh-206px)]"
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

            {/* 元数据弹窗 */}
            <Dialog open={metadataDialog.open} onOpenChange={(open) => setMetadataDialog(prev => ({ ...prev, open }))}>
                <DialogContent className="sm:max-w-[625px]">
                    <DialogHeader>
                        <h3 className="text-lg font-semibold">{t('文档元数据')}</h3>
                    </DialogHeader>
                    {console.log(metadataDialog.file, 67678)}
                    <div className="grid gap-4 py-4 max-h-[60vh] overflow-y-auto pr-2">
                        <div className="space-y-2">
                            {[
                                {
                                    label: t('文件名称'),
                                    value: metadataDialog.file?.file_name,
                                    isFileName: true
                                },
                                { label: t('原始文件大小'), value: metadataDialog.file?.file_size ? formatFileSize(metadataDialog.file.file_size) : null },
                                {
                                    label: t('创建时间'),
                                    value: metadataDialog.file?.create_time ? metadataDialog.file.create_time.replace('T', ' ') : null
                                },
                                {
                                    label: t('更新时间'),
                                    value: metadataDialog.file?.update_time ? metadataDialog.file.update_time.replace('T', ' ') : null
                                },
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
        </div>
    );
}