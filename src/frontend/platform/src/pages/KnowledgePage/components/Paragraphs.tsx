import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronDown, ChevronUp, FileText, Search } from 'lucide-react';
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm';
import { Button } from '@/components/bs-ui/button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Dialog, DialogContent, DialogHeader } from '@/components/bs-ui/dialog';
import { SearchInput } from '@/components/bs-ui/input';
import AutoPagination from '@/components/bs-ui/pagination/autoPagination';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select';
import { LoadingIcon } from '@/components/bs-icons/loading';
import { delChunkApi, getFilePathApi, getKnowledgeChunkApi, previewFileSplitApi, readFileByLibDatabase } from '@/controllers/API';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useTable } from '@/util/hook';
import useKnowledgeStore from '../useKnowledgeStore';
import ParagraphEdit from './ParagraphEdit';
import PreviewParagraph from './PreviewParagraph';
import PreviewFile from './PreviewFile';
import { truncateString } from "@/util/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@radix-ui/react-dropdown-menu';
import { FileIcon } from "@/components/bs-icons/file";


export default function Paragraphs({ fileId }) {
    const { t } = useTranslation('knowledge');
    const { id } = useParams();
    const navigate = useNavigate();
    const { isEditable } = useKnowledgeStore();

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
    const [isInitializing, setIsInitializing] = useState(true);
    const [selectError, setSelectError] = useState(null);
    const [isFetchingUrl, setIsFetchingUrl] = useState(false);
    const [filesLoaded, setFilesLoaded] = useState(false);

    // Refs
    const isMountedRef = useRef(true);
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const searchInputRef = useRef(null);



    // 获取文件URL
    const fetchFileUrl = useCallback(async (fileId) => {
        console.log('获取文件URL:', fileId);

        if (!fileId) return;

        try {
            setIsFetchingUrl(true);
            const res = await getFilePathApi(fileId);
            console.log(res);

            if (isMountedRef.current) {
                console.log('获取文件URL成功:', res);

                setFileUrl(res || '');
                setCurrentFile(prev => ({ ...prev, url: res }));
            }
        } catch (err) {
            console.error('获取文件URL失败:', err);
            if (isMountedRef.current) {
                setFileUrl('');
            }
        } finally {
            setIsFetchingUrl(false);
        }
    }, []);

    // 加载文件预览数据
    const loadFilePreview = useCallback(async (file) => {
        if (!file || !isMountedRef.current) return null;

        try {
            const res = await previewFileSplitApi({
                knowledge_id: id,
                file_list: [{
                    file_path: file?.filePath || '',
                    excel_rule: {}
                }]
            });

            if (res && res !== 'canceled') {
                return {
                    chunks: (res.chunks || []).map(chunk => ({
                        ...chunk,
                        bbox: chunk?.metadata?.bbox || {},
                        activeLabels: {},
                        chunkIndex: chunk?.metadata?.chunk_index || 0,
                        page: chunk?.metadata?.page || 0
                    })),
                    partitions: res.partitions || {}
                };
            }
            return null;
        } catch (err) {
            console.error('File preview failed:', err);
            return null;
        }
    }, [id]);
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

        try {
            setSelectError(null);
            setSelectedFileId(newFileId);

            const selectedFile = rawFiles.find(f => String(f.id) === String(newFileId));
            if (!selectedFile) throw new Error('未找到选中的文件');

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

            // 并行获取数据
            await Promise.all([
                fetchFileUrl(selectedFile.id),
                loadFilePreview(selectedFile).then(data => {
                    if (data) {
                        setChunks(data.chunks || []);
                        setPartitions(data.partitions || {});
                    }
                })
            ]);

            // 强制刷新表格数据
            filterData && filterData({ file_ids: [newFileId] });
            reload(); // 确保数据刷新

        } catch (err) {
            console.error('文件切换失败:', err);
            setSelectError(err.message || '文件切换失败');
            setFileUrl('');
        }
    }, [rawFiles, fetchFileUrl, loadFilePreview, filterData, reload]);



    // 加载文件列表
    useEffect(() => {
        const loadFiles = async () => {
            try {
                setIsInitializing(true);
                const res = await readFileByLibDatabase({
                    id,
                    page: 1,
                    pageSize: 4000,
                    status: 2
                });
                const filesData = res?.data || [];
                console.log('filesData', filesData);

                setRawFiles(filesData);

                if (filesData.length) {
                    const defaultFileId = fileId ? String(fileId) : String(filesData[0]?.id || '');
                    setSelectedFileId(defaultFileId);

                    // 立即设置currentFile而不等待handleFileChange
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
                        setCurrentFile(fileData); // 立即设置当前文件

                        // 立即触发文件URL获取
                        fetchFileUrl(selectedFile.id);

                        // 立即触发文件预览加载
                        loadFilePreview(selectedFile).then(data => {
                            if (data) {
                                setChunks(data.chunks || []);
                                setPartitions(data.partitions || {});
                            }
                        });
                    }

                    // 强制刷新表格数据
                    filterData && filterData({ file_ids: [defaultFileId] });
                    reload(); // 确保数据刷新
                }
                setFilesLoaded(true);
            } catch (err) {
                console.error('Failed to load files:', err);
                setSelectError('加载文件列表失败');
            } finally {
                setIsInitializing(false);
            }
        };

        loadFiles();

        return () => {
            isMountedRef.current = false;
        };
    }, [id, fileId]);

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
        return (datalist || []).map((item, index) => ({
            text: item?.text || '',
            title: `分段${index + 1}`,
            chunkIndex: item?.metadata?.chunk_index || index,
            metadata: item?.metadata || {}
        }));
    }, [datalist]);

    const handleMetadataClick = useCallback(() => {
        if (currentFile?.fullData) {
            setMetadataDialog({
                open: true,
                file: currentFile.fullData
            });
        }
    }, [currentFile]);


    const handleAdjustSegmentation = useCallback(() => {
        console.log(selectedFileId, currentFile, '098');

        navigate(`/filelib/upload/${id}`, {
            state: {
                skipToStep: 2,
                fileId: selectedFileId,
                fileData: { // 确保传递正确的数据结构
                    id: currentFile.id,
                    name: currentFile.name,
                    filePath: currentFile.filePath,
                    suffix: currentFile.suffix,
                    fileType: currentFile.fileType
                },
                isAdjustMode: true
            }
        });
    }, [id, selectedFileId, currentFile, navigate]);

    const handleDeleteChunk = useCallback((data) => {
        captureAndAlertRequestErrorHoc(delChunkApi({
            knowledge_id: id,
            file_id: data?.metadata?.file_id || '',
            chunk_index: data?.metadata?.chunk_index || 0
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
    return (
        <div className="relative">
            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
            )}

            <div className="absolute left-10 right-0 top-[-62px] flex justify-between items-center px-4">
                <div className="min-w-72 max-w-[400px]">
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
                                            onChange={(e) => setSearchTerm(e.target.value)}
                                        />
                                    </div>
                                </div>
                                <div className="max-h-[300px] overflow-y-auto">
                                    {filteredFiles.map((file) => (
                                        <DropdownMenuItem
                                            key={file.value}
                                            onSelect={() => {
                                                handleFileChange(file.value);
                                                setSearchTerm("");
                                            }}
                                            disabled={!file.value}
                                            className="cursor-pointer hover:bg-gray-50 px-3 py-2"
                                        >
                                            <div className="flex items-center gap-3 w-full h-full">
                                                <FileIcon
                                                    type={file.label.split('.').pop().toLowerCase() || 'txt'}
                                                    className="size-[30px] min-w-[30px]  text-current"
                                                />
                                                <span className="flex-1 min-w-0 truncate">
                                                    {truncateString(file.label, 35)}
                                                </span>
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

            <div className="flex bg-background-main">

                {selectedFileId && currentFile && fileUrl ? (

                    <PreviewFile
                        key={`preview-${currentFile.id}`}
                        urlState={{ load: !isFetchingUrl, url: fileUrl }}
                        file={currentFile}
                        chunks={safeChunks}
                        setChunks={setChunks}
                        partitions={partitions}
                        h={false}
                    />

                ) : (
                    <div className="flex justify-center items-center h-full text-gray-400">
                        <FileText width={160} height={160} className="text-border" />
                        {selectError || t('noFileSelected')}
                    </div>
                )}


                <div className="w-1/2 overflow-y-auto pb-20">
                    <div className="flex flex-wrap gap-2 p-2 items-start">
                        {datalist.length ? (
                            <PreviewParagraph
                                fileId={selectedFileId}
                                previewCount={datalist.length}
                                edit={isEditable}
                                fileSuffix={currentFile?.suffix || ''}
                                loading={loading}
                                chunks={safeChunks}
                                onDel={handleDeleteChunk}
                                onChange={(index, newText) => {
                                    refreshData(
                                        (item) => item?.metadata?.chunk_index === datalist[index]?.metadata?.chunk_index,
                                        { text: newText }
                                    );
                                }}
                            />
                        ) : (
                            <div className="flex justify-center items-center flex-col size-full text-gray-400">
                                <FileText width={160} height={160} className="text-border" />
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <div className="bisheng-table-footer px-6">
                <AutoPagination
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
                                { label: t('文件名称'), value: metadataDialog.file?.file_name },
                                { label: t('原始文件大小'), value: metadataDialog.file?.size ? formatFileSize(metadataDialog.file.size) : null },
                                { label: t('创建时间'), value: metadataDialog.file?.create_time },
                                { label: t('更新时间'), value: metadataDialog.file?.update_time },
                                { label: t('切分策略'), value: metadataDialog.file?.split_rule },
                                { label: t('全文摘要'), value: metadataDialog.file?.tilte }
                            ].map((item, index) => (
                                item.value && (
                                    <div key={index} className="grid grid-cols-4 gap-4 items-center">
                                        <span className="text-sm text-muted-foreground col-span-1">{item.label}</span>
                                        <span className="col-span-3 text-sm">{item.value || t('none')}</span>
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