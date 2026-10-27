import { notification } from '@bisheng/ui';
// @ts-strict-ignore
import { Button, SearchInput } from '@bisheng/ui';
import { FileIcon } from "@/components/bs-icons/file";

import { Dialog,DialogContent } from '@/components/bs-ui/dialog';

import AutoPagination from '@/components/bs-ui/pagination/autoPagination';

import { delChunkApi,getFileBboxApi,getFilePathApi,getKnowledgeChunkApi,readFileByLibDatabase,updateChunkApi } from '@/controllers/API';
import { showApiError } from '@/controllers/request';
import { useTable } from '@/util/hook';
import { Outlined } from "bisheng-icons";
import { useCallback,useEffect,useMemo,useRef,useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation,useNavigate,useParams } from 'react-router-dom';
import { useParagraphMetadata } from "../hooks/useParagraphMetadata";
import useKnowledgeStore from '../useKnowledgeStore';
import FileSelector from "./FileSelector";
import { KnowledgeTooltip } from "./KnowledgeTooltip";
import { MainMetadataDialog,MetadataSideDialog } from './MetadataDialog';
import ParagraphEdit from './ParagraphEdit';
import PreviewFile from './PreviewFile';
import PreviewParagraph from './PreviewParagraph';
export default function Paragraphs({ fileId, onBack, canEditKb = false, canDeleteKb = false }) {
    console.log('Props fileId:', fileId);
    const { t } = useTranslation('knowledge');
    const { id } = useParams();
    const navigate = useNavigate();
    const { selectedBbox } = useKnowledgeStore();
    const [hasInited, setHasInited] = useState(false);
    const location = useLocation();
    const [chunkSwitchTrigger, setChunkSwitchTrigger] = useState(0);
    const [selectedFileId, setSelectedFileId] = useState(fileId + '');
    const [currentFile, setCurrentFile] = useState(null);
    const [fileUrl, setFileUrl] = useState('');
    const [chunks, setChunks] = useState([]);
    const [rawFiles, setRawFiles] = useState([]);
    const isKnowledgeAdmin = canEditKb;
    const { metadataDialog, setMetadataDialog, mainMetadataList, newMetadata, setNewMetadata, metadataError, setMetadataError, sideDialog, setSideDialog, predefinedMetadata, searchTerm, setSearchTerm, fileInfor, mainMetadataDialogRef, sideDialogPosition, isSmallScreen, sideDialogWidth, isSideDialogPositioned, handleDeleteMainMetadata, handleMainMetadataValueChange, handleSaveNewMetadata, handleSearchMetadataClick, handleCreateMetadataClick, closeSideDialog, handleAddFromSearch, handleMetadataClick, handleSaveUserMetadata, splitRuleDesc, formatFileSize } = useParagraphMetadata({ id, selectedFileId, currentFile, canEditKb, t, notify: notification.open });
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
    const isChangingRef = useRef(false);
    const [previewUrl, setPreviewUrl] = useState()
    const [previewData, setPreviewData] = useState<any>(null)
    const [hasChunkBboxes, setHasChunkBboxes] = useState(false);
    const latestFileUrlRef = useRef('');
    const latestPreviewUrlRef = useRef('');
    const latestOriginalUrlRef = useRef('');
    const selectedChunkIndex = useKnowledgeStore((state) => state.selectedChunkIndex);
    const setSelectedBbox = useKnowledgeStore((state) => state.setSelectedBbox);
    useEffect(() => {
        setSelectedBbox([])
    }, [selectedChunkIndex])
    const tableConfig = useMemo(() => ({
        file_ids: selectedFileId ? [selectedFileId] : [],
        unInitData: true
    }), [selectedFileId]);
    const fetchAllFiles = useCallback(async () => {
        try {
            const res = await readFileByLibDatabase({
                id: id,
                page: 1,
                pageSize: 1000, // 获取足够多的文件
                name: '',
                status: 2
            });
            const filesData = res?.data || [];
            setRawFiles(filesData);
            console.log('Fetched all files:', filesData.length);
            if (fileId && filesData.length > 0 && !currentFile) {
                const foundFile = filesData.find(f => String(f.id) === String(fileId));
                if (foundFile) {
                    setCurrentFile({
                        label: foundFile.file_name || '',
                        value: fileId,
                        id: foundFile.id || '',
                        name: foundFile.file_name || '',
                        size: foundFile.size || 0,
                        type: foundFile.file_name?.split('.').pop() || '',
                        filePath: '',
                        suffix: foundFile.file_name?.split('.').pop() || '',
                        fileType: foundFile.parse_type || 'unknown',
                        fullData: foundFile || {},
                    });
                }
            }
        } catch (error) {
            console.error('Failed to fetch all files:', error);
        }
    }, [id, fileId, currentFile]);
    useEffect(() => {
        if (id) {
            fetchAllFiles();
        }
    }, [id, fetchAllFiles]);
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
                        console.log('bbox is empty string');
                        chunkBboxes = [];
                    } else {
                        const bboxObj = JSON.parse(firstChunk.metadata.bbox);
                        chunkBboxes = bboxObj.chunk_bboxes || [];
                    }
                }
            } catch (e) {
                console.error('Failed to parse chunk_bboxes:', e);
                chunkBboxes = [];
            }
            const isBboxesNotEmpty = Array.isArray(chunkBboxes) && chunkBboxes.length > 0;
            setHasChunkBboxes(isBboxesNotEmpty);
            console.log('chunk_bboxes is not empty:', isBboxesNotEmpty, 'Original data:', chunkBboxes);
            return response;
        }
    );
    const [load, setLoad] = useState(true);
    const safeChunks = useMemo(() => {
        if (!selectedFileId || !datalist.length) return [];
        return (datalist || []).map((item, index) => ({
            text: item?.text || '',
            title: `Segment ${index + 1}`,
            chunkIndex: item?.metadata?.chunk_index || index,
            bbox: item?.metadata?.bbox
        }));
    }, [datalist, selectedFileId, chunkSwitchTrigger]);
    const handleChunkChange = useCallback((chunkIndex, text) => {
        if (!canEditKb) return;
        const chunkIndexPage = chunkIndex % pageSize;
        console.log('Converted localIndex:', chunkIndexPage);
        const bbox = { chunk_bboxes: selectedBbox };
        const bboxStr = selectedBbox.length ? JSON.stringify(bbox) : safeChunks[chunkIndexPage]?.bbox || '';
        updateChunkApi({
            knowledge_id: Number(id),
            file_id: selectedFileId || currentFile?.id || '',
            chunk_index: chunkIndex,
            text,
            bbox: bboxStr
        }).then(() => {
        setChunks(chunks => chunks.map(chunk =>
            chunk.chunkIndex === chunkIndex ? { ...chunk, bbox: bboxStr, text } : chunk
        ));
        refreshData(
            (item) => item?.metadata?.chunk_index === chunkIndex,
            (item) => ({ text, metadata: { ...item.metadata, bbox: bboxStr } })
        );
        }).catch(showApiError)
    }, [canEditKb, id, currentFile, refreshData, selectedBbox, safeChunks, pageSize, selectedFileId]);
    const fetchFileUrl = useCallback(async (fileId) => {
        console.log('Getting file URL:', fileId);
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
            setPreviewData({
                ...res,
                original_url: res.original_url || '',
                preview_url: res.preview_url || '',
                file_source: res.file_source || '',
                source_url: res.source_url || '',
                final_url: res.final_url || '',
                web_title: res.web_title || '',
                media_kind: res.media_kind || '',
                html_preview_url: res.html_preview_url || '',
            });
            if (currentFile) {
                if (hasPreviewUrl) {
                    finalUrl = res.preview_url.trim();
                    finalPreviewUrl = res.preview_url.trim();
                } else {
                    finalUrl = hasOriginalUrl ? res.original_url.trim() : '';
                    finalPreviewUrl = finalUrl;
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
                setPreviewData(null);
                latestOriginalUrlRef.current = '';
                return '';
            }
        } catch (err) {
            console.error('Failed to get file URL:', err);
            setFileUrl('');
            setPreviewUrl('');
            setPreviewData(null);
            setPartitions([]);
            latestOriginalUrlRef.current = '';
            return '';
        } finally {
            setIsFetchingUrl(false);
        }
    }, [rawFiles, hasChunkBboxes]);
    useEffect(() => {
        const pathName = location.pathname.replace(__APP_ENV__.BASE_URL, '')
        if (pathName.startsWith('/filelib/adjust/') && !window.history.state?.isAdjustMode) {
            const adjustId = pathName.split('/')[3];
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
            chunkIndex: item.metadata?.chunk_index || index,
            page: item.metadata?.page || 0,
            metadata: item.metadata || {}
        }));
        setChunks(generatedChunks);
    }, [datalist, selectedFileId]);
    const handleFileChange = useCallback(async (newFileId, selectedFile) => {
        console.log('File change triggered:', newFileId, 'Current selected:', selectedFile);
        if (selectedFile) {
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
                fullData: selectedFile || {},
            });
            setSelectedFileId(newFileId);
        }
        isChangingRef.current = true;
        setSelectError(null);
        setIsFetchingUrl(true);
        setChunks([]);
        setFileUrl('');
        setPreviewUrl('');
        latestOriginalUrlRef.current = '';
        try {
            if (filterData) filterData({ file_ids: [newFileId] });
            await fetchFileUrl(newFileId);
            if (!filterData) await reload();
            setChunkSwitchTrigger(prev => prev + 1);
        } catch (err) {
            console.error('File change failed:', err);
            setSelectError(err.message || t('file.changeFailed'));
        } finally {
            setIsFetchingUrl(false);
            isChangingRef.current = false;
            setLoad(false);
        }
    }, [rawFiles, fetchFileUrl, filterData, reload, selectedFileId, fileUrl, previewUrl, t]);
    useEffect(() => {
        if (fileId && !selectedFileId) {
            setSelectedFileId(String(fileId));
        }
    }, [fileId, selectedFileId]);
    const handleAdjustSegmentation = useCallback(() => {
        if (!canEditKb) return;
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
    }, [canEditKb, id, selectedFileId, currentFile, navigate]);
    const handleDeleteChunk = useCallback(async (data) => {
        if (!canDeleteKb) return;
        try {
            const updatedChunks = chunks.filter(chunk => chunk.chunkIndex !== data);
            setChunks(updatedChunks);
            if (selectedChunkIndex === data) {
                setSelectedBbox([]);
            }
            await delChunkApi({
                knowledge_id: Number(id),
                file_id: selectedFileId || currentFile?.id || '',
                chunk_index: data || 0
            });
            await new Promise(resolve => setTimeout(resolve, 100));
            await reload();
        } catch (error) {
            showApiError(error);
            setChunks(chunks);
            await reload();
        }
    }, [
        canDeleteKb,
        id,
        reload,
        chunks,
        selectedFileId,
        currentFile?.id,
        selectedChunkIndex,
        setSelectedBbox,
        t
    ]);
    const previewRules = useMemo(() => ({
        fileList: currentFile ? [{
            id: currentFile.id,
            filePath: fileUrl,
            fileName: currentFile.name,
            suffix: currentFile.suffix,
            fileType: currentFile.fileType,
            excelRule: {} // Add excel rules as needed
        }] : [],
        pageHeaderFooter: false, // Page header/footer processing
        chunkOverlap: 200, // Chunk overlap size
        chunkSize: 1000, // Chunk size
        enableFormula: false, // Whether to enable formulas
        forceOcr: false, // Whether to force OCR
        knowledgeId: id, // Knowledge base ID
        retainImages: false, // Whether to retain images
        separator: [], // Separators
        separatorRule: [] // Separation rules
    }), [currentFile, fileUrl, id]);
    const isPreviewVisible =
        selectedFileId &&
        currentFile &&
        (previewUrl || fileUrl) && // Compatible with either previewUrl or fileUrl having value
        !isFetchingUrl;
    const isParagraphVisible = datalist.length > 0;
    const contentLayoutClass = useMemo(() => {
        const isSingleVisible = isPreviewVisible !== isParagraphVisible;
        if (isSingleVisible) {
            return "flex justify-center bg-background-main min-h-0";
        }
        return "flex bg-background-main min-h-0";
    }, [isPreviewVisible, isParagraphVisible,]);
    useEffect(() => {
        latestFileUrlRef.current = fileUrl;
        latestPreviewUrlRef.current = previewUrl;
    }, [fileUrl, previewUrl]);
    const handleWriteableChange = () => {}
    return (
        <div className="relative flex flex-col h-[calc(100vh-64px-var(--license-banner-h,0px))]">
            {load && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,1)] dark:bg-blur-shared">
                <Outlined.Loading  className="size-4 animate-spin"/>
            </div>}
            {/* Top navigation bar */}
            <div className="flex justify-between items-center px-4 pt-4 pb-4">
                <div className="min-w-72 max-w-[440px] flex items-center gap-2">
                    <KnowledgeTooltip content={t('common.back')} side="top">
                        <button
                            className="extra-side-bar-buttons w-[36px] max-h-[36px]"
                            onClick={onBack}
                        >
                            <Outlined.ArrowLeft className="side-bar-button-size" />
                        </button>
                    </KnowledgeTooltip>
                    <FileSelector
                        knowledgeId={id}
                        selectedFileId={selectedFileId}
                        onWriteableChange={handleWriteableChange}
                        onFileChange={handleFileChange}
                        disabled={false}
                    />
                </div>
                <div className="flex items-center gap-2 ml-auto">
                    <div className="w-60">
                        <SearchInput placeholder={t('segment.searchSegments')} onChange={(e) => search(e.target.value)} disabled={!selectedFileId} />
                    </div>
                    {canEditKb && (
                    <Button variant="outlined" onClick={handleMetadataClick} className="whitespace-nowrap" color="default">
                        <Outlined.FileEditing size={16} strokeWidth={1.5} className="mr-1" />
                        {t('metadialog.title')}
                    </Button>
                    )}
                    {canEditKb && (
                        <Button onClick={handleAdjustSegmentation} className="whitespace-nowrap">
                            {t('segment.adjustStrategy')}
                        </Button>
                    )}
                </div>
            </div>
            {/* Main content area */}
            <div className={contentLayoutClass}>
                {/* Preview component - fix display issues */}
                {isPreviewVisible ? (
                    <PreviewFile
                        rawFiles={rawFiles}
                        key={selectedFileId}
                        partitions={partitions}
                        previewUrl={previewUrl}
                        urlState={{ load: !isFetchingUrl, url: previewUrl || fileUrl }}
                        file={currentFile}
                        chunks={chunks}
                        setChunks={setChunks}
                        previewData={previewData}
                        rules={previewRules}
                        edit={canEditKb}
                    />
                ) : (
                    !isParagraphVisible && (
                        <div className="flex justify-center items-center h-[400px] text-gray-500 bg-gray-50 rounded-lg w-full max-w-4xl">
                            <FileIcon className="size-8 mb-3 opacity-50" />
                            <p className="text-lg font-medium">{t('file.previewNotAvailable')}</p>
                        </div>
                    )
                )}
                {/* Segment component */}
                {isParagraphVisible ? (
                    <div className={isPreviewVisible ? "w-1/2" : " w-full max-w-3xl"}>
                        <div className="flex justify-center items-center relative text-sm gap-2 p-2 pt-0 ">
                            <PreviewParagraph
                                key={`preview-${selectedFileId}-${chunkSwitchTrigger}`}
                                fileId={selectedFileId}
                                previewCount={datalist.length}
                                edit={canEditKb}
                                canDelete={canDeleteKb}
                                page={page}
                                className="h-[calc(100vh-206px-var(--license-banner-h,0px))] pb-6"
                                fileSuffix={currentFile?.suffix || ''}
                                loading={loading}
                                chunks={chunks}
                                onDel={handleDeleteChunk}
                                onChange={handleChunkChange}
                            />
                        </div>
                    </div>
                ) : (
                    !isPreviewVisible && (
                        <div className="flex justify-center items-center flex-col h-[400px] text-gray-500 bg-gray-50 rounded-lg w-full max-w-4xl">
                            <Outlined.FileTxt className="size-8 mb-3 opacity-50" />
                            <p className="text-lg font-medium">{t('segment.noData')}</p>
                        </div>
                    )
                )}
            </div>
            {/* Pagination */}
            <div className="bisheng-table-footer px-6">
                <AutoPagination
                    className="justify-end"
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    showTotal={true}
                    onChange={setPage}
                    disabled={!selectedFileId}
                />
            </div>
            <MainMetadataDialog
                metadataDialog={metadataDialog}
                setMetadataDialog={setMetadataDialog}
                mainMetadataList={mainMetadataList}
                fileInfor={fileInfor}
                isKnowledgeAdmin={isKnowledgeAdmin}
                isSmallScreen={isSmallScreen}
                t={t}
                formatFileSize={formatFileSize}
                splitRuleDesc={splitRuleDesc}
                handleSaveUserMetadata={handleSaveUserMetadata}
                handleSearchMetadataClick={handleSearchMetadataClick}
                handleDeleteMainMetadata={handleDeleteMainMetadata}
                handleMainMetadataValueChange={handleMainMetadataValueChange}
                mainMetadataDialogRef={mainMetadataDialogRef}
            />
            {/* Segment editing dialog */}
            <Dialog open={paragraph.show} onOpenChange={(show) => setParagraph(prev => ({ ...prev, show }))}>
                <DialogContent close={false} className='size-full max-w-full sm:rounded-none p-0 border-none'>
                    <ParagraphEdit
                        edit={canEditKb}
                        fileId={paragraph.fileId}
                        chunkId={paragraph.chunkId}
                        isUns={paragraph.isUns || ['etl4lm', 'un_etl4lm', 'mineru', 'mineru_v4'].includes(paragraph.parseType)}
                        parseType={paragraph.parseType}
                        onClose={() => setParagraph(prev => ({ ...prev, show: false }))}
                        onChange={(value) => refreshData(
                            (item) => item?.metadata?.chunk_index === paragraph.chunkId,
                            { text: value }
                        )}
                    />
                </DialogContent>
            </Dialog>
            {/* Right metadata sidebar dialog */}
            <MetadataSideDialog
                sideDialog={sideDialog}
                closeSideDialog={closeSideDialog}
                predefinedMetadata={predefinedMetadata}
                searchTerm={searchTerm}
                setSearchTerm={setSearchTerm}
                newMetadata={newMetadata}
                setNewMetadata={setNewMetadata}
                metadataError={metadataError}
                setMetadataError={setMetadataError}
                isKnowledgeAdmin={isKnowledgeAdmin}
                isSmallScreen={isSmallScreen}
                t={t}
                sideDialogWidth={sideDialogWidth}
                sideDialogPosition={sideDialogPosition}
                isSideDialogPositioned={isSideDialogPositioned}
                handleAddFromSearch={handleAddFromSearch}
                handleCreateMetadataClick={handleCreateMetadataClick}
                handleSaveNewMetadata={handleSaveNewMetadata}
                setSideDialog={setSideDialog}
            />
        </div>
    );
}
