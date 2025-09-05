import { FileIcon } from "@/components/bs-icons/file";
import { LoadingIcon } from '@/components/bs-icons/loading';
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogHeader } from '@/components/bs-ui/dialog';
import { SearchInput } from '@/components/bs-ui/input';
import AutoPagination from '@/components/bs-ui/pagination/autoPagination';
import { delChunkApi, getFilePathApi, getKnowledgeChunkApi, previewFileSplitApi, readFileByLibDatabase, updateChunkApi } from '@/controllers/API';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useTable } from '@/util/hook';
import { truncateString } from "@/util/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@radix-ui/react-dropdown-menu';
import { ArrowLeft, ChevronDown, ChevronUp, FileText, Search } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import useKnowledgeStore from '../useKnowledgeStore';
import ParagraphEdit from './ParagraphEdit';
import PreviewFile from './PreviewFile';
import PreviewParagraph from './PreviewParagraph';
import ShadTooltip from "@/components/ShadTooltipComponent";


export default function Paragraphs({ fileId, onBack }) {

    const { t } = useTranslation('knowledge');
    const { id } = useParams();
    const navigate = useNavigate();
    const { isEditable, selectedBbox } = useKnowledgeStore();

    // State management
    const [selectedFileId, setSelectedFileId] = useState('');
    const [currentFile, setCurrentFile] = useState(null);
    const [fileUrl, setFileUrl] = useState(''); // 简化为单个URL状态
    const [chunks, setChunks] = useState([]);
    const [partitions, setPartitions] = useState({});
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

    // Refs
    const isMountedRef = useRef(true);
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const searchInputRef = useRef(null);



    // 获取文件URL
    const fetchFileUrl = useCallback(async (fileId) => {
        console.log('获取文件URL:', fileId);

        if (!fileId) return '';

        try {
            setIsFetchingUrl(true);
            console.log('调用 getFilePathApi 前:', fileId);

            const res = await getFilePathApi(fileId);
            console.log('getFilePathApi 响应:', res);

            if (isMountedRef.current) {
                console.log('获取文件URL成功:', res);
                const url = res.data || res.url || res.filePath || res;
                setFileUrl(url || '');
                setCurrentFile(prev => prev ? { ...prev, url } : null);
                return url; // 返回获取到的 URL
            }
            return '';
        } catch (err) {
            console.error('获取文件URL失败:', err);
            if (isMountedRef.current) {
                setFileUrl('');
            }
            return '';
        } finally {
            setIsFetchingUrl(false);
        }
    }, []);


    // 加载文件预览数据
    const loadFilePreview = useCallback(async (file, currentFileUrl) => {
        if (!file || !isMountedRef.current) return null;
        console.log('加载预览数据 - URL:', currentFileUrl, 'split_rule:', file.split_rule);

        try {
            let excelRule = {};
            try {
                if (file.split_rule) {
                    excelRule = typeof file.split_rule === 'string'
                        ? JSON.parse(file.split_rule)
                        : file.split_rule;
                }
            } catch (parseError) {
                console.error('解析 split_rule 失败:', parseError);
                excelRule = {};
            }

            const res = await previewFileSplitApi({
                knowledge_id: id,
                file_list: [{
                    file_path: file?.filePath || currentFileUrl || '',
                    excel_rule: excelRule || {}
                }]
            });

            if (res && res !== 'canceled' && res.chunks) {
                // 确保返回的 chunks 结构正确，避免空数据
                return {
                    chunks: res.chunks.map(chunk => ({
                        ...chunk,
                        bbox: chunk?.metadata?.bbox || {},
                        activeLabels: {},
                        chunkIndex: chunk?.metadata?.chunk_index || 0,
                        page: chunk?.metadata?.page || 0,
                        text: chunk.text || '' // 兜底：确保 text 字段存在，避免 PreviewParagraph 报错
                    })),
                    partitions: res.partitions || {}
                };
            }
            throw new Error('预览接口返回数据异常');
        } catch (err) {
            console.error('File preview failed:', err);
            return null;
        }
    }, [id]); // 仅保留必要的 id 依赖，移除 chunks
    // 表格配置
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
    // 处理文件切换
const handleFileChange = useCallback(async (newFileId) => {
  if (!newFileId || !isMountedRef.current) return;

  // 1. 切换前先重置错误状态和加载中的临时状态
  setSelectError(null);
  setIsFetchingUrl(true); // 新增：显示加载中，避免用户重复操作

  try {
    // 2. 先找到选中的文件（同步操作，确保文件信息存在）
    const selectedFile = rawFiles.find(f => String(f.id) === String(newFileId));
    if (!selectedFile) throw new Error('未找到选中的文件');

    // 3. 先刷新表格数据（filterData + reload），等待表格数据更新完成
    // （关键：表格数据是 safeChunks 的来源，必须先更新）
    if (filterData) filterData({ file_ids: [newFileId] });
    await reload(); // 等待表格数据刷新完成

    // 4. 再获取文件URL（依赖选中文件的id）
    const fileUrlResult = await fetchFileUrl(selectedFile.id);
    if (!fileUrlResult) throw new Error('获取文件URL失败');

    // 5. 再加载预览数据（依赖URL）
    const previewData = await loadFilePreview(selectedFile, fileUrlResult);

    // 6. 最后更新所有状态（确保所有异步操作完成后，再更新UI依赖的状态）
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
      url: fileUrlResult // 新增：将URL存入currentFile，避免后续取值为空
    };
    setCurrentFile(fileData);
    setFileUrl(fileUrlResult);
    setSelectedFileId(newFileId); // 最后更新selectedFileId，触发UI重新渲染
    if (previewData) {
      setChunks(previewData.chunks || []);
      setPartitions(previewData.partitions || {});
    }

  } catch (err) {
    console.error('文件切换失败:', err);
    setSelectError(err.message || '文件切换失败');
    // 错误时重置状态，避免组件卡在错误状态
    setSelectedFileId('');
    setCurrentFile(null);
    setFileUrl('');
  } finally {
    setIsFetchingUrl(false); // 结束加载状态
  }
}, [rawFiles, fetchFileUrl, loadFilePreview, filterData, reload]);




    useEffect(() => {
        console.log('selectedFileId 变化:', selectedFileId);
        console.log('currentFile 状态:', currentFile);
        console.log('fileUrl 状态:', fileUrl);
    }, [selectedFileId, currentFile, fileUrl]);
    // 加载文件列表
    useEffect(() => {
        const loadFiles = async () => {
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
                    setSelectedFileId(defaultFileId);

                    const selectedFile = filesData.find(f => String(f.id) === defaultFileId);
                    if (selectedFile) {
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
                            fullData: selectedFile || {}
                        };
                        setCurrentFile(fileData);

                        // 获取文件URL并等待完成
                        const fileUrlResult = await fetchFileUrl(selectedFile.id);

                        // 使用获取到的 fileUrl 加载预览
                        const previewData = await loadFilePreview(selectedFile, fileUrlResult);
                        if (previewData) {
                            setChunks(previewData.chunks || []);
                            setPartitions(previewData.partitions || {});
                        }
                    }

                    // 强制刷新表格数据
                    filterData && filterData({ file_ids: [defaultFileId] });
                    reload();
                }
            } catch (err) {
                console.error('Failed to load files:', err);
                setSelectError('加载文件列表失败');
            }
        };

        loadFiles();

        return () => {
            isMountedRef.current = false;
        };
    }, [id, fileId]);

    const handleChunkChange = useCallback((chunkIndex, text) => {
        const bbox = { chunk_bboxes: selectedBbox }; // 直接使用 selectedBbox

        captureAndAlertRequestErrorHoc(updateChunkApi({
            knowledge_id: Number(id),
            file_id: selectedFileId || currentFile?.id || '',
            chunk_index: chunkIndex,
            text,
            bbox: JSON.stringify(bbox)
        }));

        // 更新本地 chunks 状态
        setChunks(chunks => chunks.map(chunk =>
            chunk.chunkIndex === chunkIndex ? { ...chunk, text } : chunk
        ));

        // 同时更新表格数据
        refreshData(
            (item) => item?.metadata?.chunk_index === chunkIndex,
            { text }
        );
    }, [id, currentFile, refreshData, selectedBbox]);

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
        // 新增：文件未选中或数据未加载时，返回空数组（避免旧数据残留）
        if (!selectedFileId || !datalist.length) return [];

        return (datalist || []).map((item, index) => ({
            text: item?.text || '',
            title: `分段${index + 1}`,
            chunkIndex: item?.metadata?.chunk_index || index,
            metadata: item?.metadata || {}
        }));
        // 关键：添加 selectedFileId 依赖，确保文件切换时强制重新计算
    }, [datalist, selectedFileId]);

    const handleMetadataClick = useCallback(() => {
        if (currentFile?.fullData) {
            setMetadataDialog({
                open: true,
                file: currentFile.fullData
            });
        }
    }, [currentFile]);


    const handleAdjustSegmentation = useCallback(() => {
        console.log(selectedFileId, currentFile,currentFile.fullData.split_rule ,'098');

        navigate(`/filelib/adjust/${id}`, {
            state: {
                skipToStep: 2,
                fileId: selectedFileId,
                fileData: { // 确保传递正确的数据结构
                    id: currentFile.id,
                    name: currentFile.name,
                    split_rule: currentFile.split_rule,
                    status: currentFile.status,
                    filePath: currentFile.url,
                    suffix: currentFile.suffix,
                    fileType: currentFile.fileType,
                    split_rule:currentFile.fullData.split_rule
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
    const handleDeleteChunk = useCallback((data) => {
        console.log(data, 89);

        captureAndAlertRequestErrorHoc(delChunkApi({
            knowledge_id: Number(id),
            file_id: selectedFileId || currentFile?.id || '',
            chunk_index: data || 0
        }));
        reload();
    }, [id, reload]);

    const formatFileSize = useCallback((bytes) => {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
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
    const isPreviewVisible = selectedFileId && currentFile && fileUrl && !isFetchingUrl;
    const isParagraphVisible = datalist.length > 0;
    const contentLayoutClass = useMemo(() => {
        if (isPreviewVisible && isParagraphVisible) {
            return "flex bg-background-main"; // 双区域显示：默认Flex
        } else if (isPreviewVisible || isParagraphVisible) {
            return "flex justify-center bg-background-main"; // 单区域显示：居中
        }
        return "flex bg-background-main"; // 都不显示：默认布局
    }, [isPreviewVisible, isParagraphVisible]);
    return (
        <div className="relative">

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
                    flex items-center gap-2 max-w-[430px] px-3 py-2 rounded-md cursor-pointer
                    hover:bg-gray-100 ${isDropdownOpen ? 'ring-1 ring-gray-300' : ''}
                `}>
                                    {selectedFileId ? (
                                        <>
                                            <FileIcon
                                                type={files.find(f => f.value === selectedFileId)?.label.split('.').pop().toLowerCase() || 'txt'}
                                                className="size-[30px] min-w-[30px]"
                                            />
                                            {truncateString(files.find(f => f.value === selectedFileId)?.label || '', 35)}
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
                                                e.preventDefault(); // 添加这行
                                            }}
                                        />
                                    </div>
                                </div>
                                <div className="max-h-[300px] overflow-y-auto">
                                    {filteredFiles.map((file) => (
                                        <DropdownMenuItem
                                            key={file.value}
                                            onClick={(e) => {
                                                e.preventDefault();
                                                console.log('选择文件:', file.value, file.label);
                                                handleFileChange(file.value);
                                                setSearchTerm("");
                                            }}
                                            disabled={!file.value}
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

            <div className={contentLayoutClass}>
                {isPreviewVisible ? ( // 优化显示条件判断
                    <PreviewFile
                        key={`preview-${currentFile.id}`}
                        urlState={{ load: !isFetchingUrl, url: fileUrl }}
                        file={currentFile}
                        chunks={safeChunks}
                        setChunks={setChunks}
                        partitions={partitions}
                        rules={previewRules}
                        h={false}
                        className={isParagraphVisible ? "w-1/2" : "w-full max-w-3xl"} // 单区域时占满宽度+限制最大宽度
                    />
                ) : (
                    <div className="flex justify-center items-center h-full text-gray-400">
                        {selectError}
                    </div>
                )}
                {isParagraphVisible  ? (
                    <div className={isPreviewVisible ? "w-1/2" : "w-full max-w-3xl"}>
                        <div className="flex flex-wrap gap-2 p-2 pt-0 items-start">
                            <PreviewParagraph
                                key={`preview-${selectedFileId}-${datalist.length}`}
                                fileId={selectedFileId}
                                previewCount={datalist.length}
                                edit={isEditable}
                                fileSuffix={currentFile?.suffix || ''}
                                loading={loading && selectedFileId === currentFile?.id}
                                chunks={safeChunks}
                                onDel={handleDeleteChunk}
                                onChange={handleChunkChange}
                            />
                        </div>
                    </div>
                ) : (
                    <div className="flex justify-center items-center flex-col h-full text-gray-400">
                        <FileText width={160} height={160} className="text-border" />
                    </div>
                )}
            </div>

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
                                        {/* 对文件名应用文本截断 */}
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