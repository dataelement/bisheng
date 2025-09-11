import { FileIcon } from "@/components/bs-icons/file";
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogHeader } from '@/components/bs-ui/dialog';
import { SearchInput } from '@/components/bs-ui/input';
import AutoPagination from '@/components/bs-ui/pagination/autoPagination';
import ShadTooltip from "@/components/ShadTooltipComponent";
import { delChunkApi, getFilePathApi, getKnowledgeChunkApi,getFileBboxApi, readFileByLibDatabase, updateChunkApi } from '@/controllers/API';
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
   const location = useLocation();
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

    // 1. 修复：URL乱码（添加decodeURIComponent）+ 确保数据顺序
    const fetchFileUrl = useCallback(async (fileId) => {
        console.log('获取文件URL:', fileId);
        if (!fileId) return '';

        try {
            setIsFetchingUrl(true);
            const res = await getFilePathApi(fileId);
            const pares = await getFileBboxApi(fileId)
            setPartitions(pares)
            console.log('getFilePathApi 响应:', res,pares);

            // 修复：提取URL并解码（解决中文/特殊字符乱码）
            let url;
            if (res.data) {
                url = res.data.url || res.data.filePath || res.data;
            } else {
                url = res.url || res.filePath || res;
            }
            const trimmedUrl = (url || '').trim();
            
            if (!trimmedUrl) {
                console.log('获取的URL为空，视为无有效URL');
                if (isMountedRef.current) {
                    setFileUrl(''); // 重置URL状态
                }
                return ''; // 返回空，标记无URL
            }
            // 关键：URL解码
            url = url ? decodeURIComponent(url) : '';

            // 成功获取URL后更新状态（保留原始逻辑）
            if (isMountedRef.current) {
                setFileUrl(url);
                setCurrentFile(prev => prev ? { ...prev, url } : null);
                console.log('文件URL获取成功:', url);
            }
            return url;

        } catch (err) {
            // 详细错误信息打印（保留原始逻辑）
            console.error('获取文件URL失败:', {
                message: err.message,
                stack: err.stack,
                response: err.response?.data,
                status: err.response?.status,
                statusText: err.response?.statusText,
                errorType: err.name
            });

            if (isMountedRef.current) {
                setFileUrl('');
            }
            return '';
        } finally {
            setIsFetchingUrl(false);
        }
    }, []);


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
    } = useTable(tableConfig, (param) =>
        getKnowledgeChunkApi({ ...param, limit: param.pageSize, knowledge_id: id })
    );
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

    // 2. 修复：下拉选择滞后（先准备数据，再统一更新UI状态）
    const handleFileChange = useCallback(async (newFileId) => {
        console.log('文件切换:', { newFileId, current: selectedFileId });
        
        // 防止重复选择和并行操作（保留原始逻辑）
        if (newFileId === selectedFileId || isChangingRef.current || !newFileId) {
            setIsDropdownOpen(false);
            return;
        }
        
        isChangingRef.current = true;
        setSelectError(null);
        setIsFetchingUrl(true);
        setChunks([]);
        setIsDropdownOpen(false); // 立即关闭下拉框（修复视觉滞后）

        try {
            // 查找选中的文件（保留原始逻辑）
            const selectedFile = rawFiles.find(f => String(f.id) === String(newFileId));
            if (!selectedFile) throw new Error('未找到选中的文件');

            // 修复：先准备数据（筛选表格+刷新+获取URL），再更新UI状态
            // 步骤1：筛选表格数据
            if (filterData) filterData({ file_ids: [newFileId] });
            // 步骤2：等待表格刷新完成（确保datalist更新）
            await reload();
            // 步骤3：获取URL（确保URL就绪）
            const fileUrlResult = await fetchFileUrl(selectedFile.id);
            // 步骤4：所有数据就绪后，再更新UI状态（避免滞后）
            const tempFileData = {
                label: selectedFile.file_name || '',
                value: String(selectedFile.id || ''),
                id: selectedFile.id || '',
                name: selectedFile.file_name || '',
                size: selectedFile.size || 0,
                type: selectedFile.file_name?.split('.').pop() || '',
                filePath: selectedFile.object_name || '',
                suffix: selectedFile.file_name?.split('.').pop() || '',
                fileType: selectedFile.parse_type || 'unknown',
                fullData: selectedFile || {},
                url: fileUrlResult // 直接用就绪的URL
            };
            // 统一更新UI状态（一次更新，避免多次渲染不一致）
            setSelectedFileId(newFileId);
            
            
            setCurrentFile(tempFileData);
            setFileUrl(fileUrlResult);

        } catch (err) {
            console.error('文件切换失败:', err);
            setSelectError(err.message || '文件切换失败');
            // 错误回滚（保留原始逻辑）
            if (isMountedRef.current) {
                setSelectedFileId('');
                setCurrentFile(null);
                setFileUrl('');
                setChunks([]);
            }
        } finally {
            setIsFetchingUrl(false);
            isChangingRef.current = false;
        }
    }, [rawFiles, fetchFileUrl, filterData, reload, selectedFileId]);

    // 加载文件列表（修复：先准备数据，再更新状态）
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

                if (filesData.length) {
                    const defaultFileId = fileId ? String(fileId) : String(filesData[0]?.id || '');
                    
                    // 修复：先准备数据（筛选+刷新+URL）
                    const selectedFile = filesData.find(f => String(f.id) === defaultFileId);
                    if (selectedFile) {
                        // 步骤1：筛选表格
                        if (filterData) filterData({ file_ids: [defaultFileId] });
                        // 步骤2：刷新表格
                        await reload();
                        // 步骤3：获取URL
                        const fileUrlResult = await fetchFileUrl(selectedFile.id);

                        // 步骤4：数据就绪后更新状态
                        const fileData = {
                            label: selectedFile.file_name || '',
                            value: String(selectedFile.id || ''),
                            id: selectedFile.id || '',
                            name: selectedFile.file_name || '',
                            size: selectedFile.size || 0,
                            type: selectedFile.file_name?.split('.').pop() || '',
                            filePath: selectedFile.object_name || '',
                            suffix: selectedFile.file_name?.split('.').pop() || '',
                            fileType: selectedFile.parse_type || 'unknown',
                            fullData: selectedFile || {},
                            url: fileUrlResult
                        };
                        setSelectedFileId(defaultFileId);
                        console.log(fileData,67);
                        setCurrentFile(fileData);
                        setFileUrl(fileUrlResult);
                    }
                }
                setIsInitReady(true);
            } catch (err) {
                console.error('加载文件失败:', err);
                setSelectError('加载文件列表失败');
                setIsInitReady(true);
            } finally {
                isLoadingFilesRef.current = false;
            }
        };

        loadFiles();

        return () => {
            isMountedRef.current = false;
        };
    }, [id, fileId, fetchFileUrl, filterData, reload]);

    // 处理分段修改（完全保留原始逻辑）
    const handleChunkChange = useCallback((chunkIndex, text) => {
        const bbox = { chunk_bboxes: selectedBbox };
        const bboxStr = JSON.stringify(bbox);

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
    }, [datalist, selectedFileId]);

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
        navigate(`/filelib/adjust/${id}`, {
            state: {
                skipToStep: 2,
                fileId: selectedFileId,
                fileData: {
                    id: currentFile?.id,
                    name: currentFile?.name,
                    split_rule: currentFile?.split_rule || currentFile?.fullData?.split_rule,
                    status: currentFile?.status,
                    filePath: currentFile?.url,
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
            if (excel_rule && ['XLSX', 'XLS', 'CSV'].includes(suffix)) {
                return `每 ${excel_rule.slice_length} 行作为一个分段`;
            }
            const { separator, separator_rule } = rule;
            if (separator && separator_rule) {
                const data = separator.map((el, i) =>
                    `${separator_rule[i] === 'before' ? '✂️' : ''}${el}${separator_rule[i] === 'after' ? '✂️' : ''}`
                );
                return data.join(', ');
            }
        } catch (e) {
            console.error('解析切分策略失败:', e);
        }
        return file.split_rule.replace(/\n/g, '\\n');
    }, []);

    // 删除分段（完全保留原始逻辑）
    const handleDeleteChunk = useCallback((data) => {
        console.log(data, 89);

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
    const isPreviewVisible = !isExcelFile && selectedFileId && currentFile  && fileUrl && !isFetchingUrl
    const isParagraphVisible = datalist.length > 0;

    // 布局类名计算（完全保留原始逻辑）
    const contentLayoutClass = useMemo(() => {
        const isSingleVisible = isPreviewVisible !== isParagraphVisible;
        if (isSingleVisible) {
            return "flex justify-center bg-background-main";
        }
        if (isPreviewVisible && isParagraphVisible && !isExcelFile) {
            return "flex bg-background-main";
        }
        return "flex bg-background-main";
    }, [isPreviewVisible, isParagraphVisible, isExcelFile]);

    // 渲染部分（完全保留原始样式，无任何修改）
    return (
        <div className="relative">
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
                                                type={files.find(f => f.value === selectedFileId)?.label.split('.').pop().toLowerCase() || 'txt'}
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
                                                e.preventDefault(); // 防止默认行为导致的问题
                                                handleFileChange(file.value);
                                                setSearchTerm("");
                                            }}
                                            className="cursor-pointer hover:bg-gray-50 px-3 py-2 relative"
                                        >
                                            <div className="flex items-center gap-3 w-full h-full">
                                                <FileIcon
                                                    type={file.label.split('.').pop().toLowerCase() || 'txt'}
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
                        urlState={{ load: !isFetchingUrl, url: fileUrl }}
                        file={currentFile}
                        chunks={safeChunks}
                        setChunks={setChunks}
                        rules={previewRules}
                        h={false}
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
                        <div className="flex justify-center items-center relative mb-2 text-sm gap-2 p-2 pt-0 ">
                            <PreviewParagraph
                                key={selectedFileId}
                                fileId={selectedFileId}
                                previewCount={datalist.length}
                                edit={isEditable}
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
                    <div className="grid gap-4 py-4">
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