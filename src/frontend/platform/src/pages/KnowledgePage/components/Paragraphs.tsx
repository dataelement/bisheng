import { FileIcon } from "@/components/bs-icons/file";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent } from '@/components/bs-ui/dialog';
import { SearchInput } from '@/components/bs-ui/input';
import AutoPagination from '@/components/bs-ui/pagination/autoPagination';
import { toast } from "@/components/bs-ui/toast/use-toast";
import Tip from "@/components/bs-ui/tooltip/tip";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { addMetadata, delChunkApi, getFileBboxApi, getFilePathApi, getKnowledgeChunkApi, getKnowledgeDetailApi, getMetaFile, readFileByLibDatabase, saveUserMetadataApi, updateChunkApi } from '@/controllers/API';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useTable } from '@/util/hook';
import { ArrowLeft, ClipboardPenLine, FileText } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import useKnowledgeStore from '../useKnowledgeStore';
import FileSelector from "./FileSelector";
import ParagraphEdit from './ParagraphEdit';
import PreviewFile from './PreviewFile';
import PreviewParagraph from './PreviewParagraph';

// Import metadata components
import { MainMetadataDialog, MetadataSideDialog } from './MetadataDialog';

export default function Paragraphs({ fileId, onBack }) {
    console.log('Props fileId:', fileId);

    const { t } = useTranslation('knowledge');
    const { id } = useParams();
    const navigate = useNavigate();
    const { isEditable, selectedBbox } = useKnowledgeStore();
    const [hasInited, setHasInited] = useState(false);
    const location = useLocation();
    const [chunkSwitchTrigger, setChunkSwitchTrigger] = useState(0);

    // State management
    const [selectedFileId, setSelectedFileId] = useState(fileId + '');
    const [currentFile, setCurrentFile] = useState(null);
    const [fileUrl, setFileUrl] = useState('');
    const [chunks, setChunks] = useState([]);
    const [rawFiles, setRawFiles] = useState([]);
    const [isKnowledgeAdmin, setIsKnowledgeAdmin] = useState(false);

    // Metadata related states
    const [metadataDialog, setMetadataDialog] = useState({
        open: false,
        file: null
    });
    const [mainMetadataList, setMainMetadataList] = useState([]);
    const [newMetadata, setNewMetadata] = useState({
        name: '',
        type: 'String'
    });
    const [metadataError, setMetadataError] = useState('');
    const [sideDialog, setSideDialog] = useState({
        type: null,
        open: false
    });
    const [predefinedMetadata, setPredefinedMetadata] = useState([]);
    const [searchTerm, setSearchTerm] = useState("");
    const [fileInfor, setFileInfor] = useState();

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

    // Refs
    const isChangingRef = useRef(false);
    const [previewUrl, setPreviewUrl] = useState()
    const [hasChunkBboxes, setHasChunkBboxes] = useState(false);
    const latestFileUrlRef = useRef('');
    const latestPreviewUrlRef = useRef('');
    const latestOriginalUrlRef = useRef('');
    const selectedChunkIndex = useKnowledgeStore((state) => state.selectedChunkIndex);

    // Right sidebar dialog related states and refs
    const mainMetadataDialogRef = useRef(null);
    const [sideDialogPosition, setSideDialogPosition] = useState({ top: 0, left: 0 });
    const [screenWidth, setScreenWidth] = useState(window.innerWidth);
    const isSmallScreen = screenWidth < 1366;
    const sideDialogWidth = isSmallScreen ? 240 : 300;
    const [isSideDialogPositioned, setIsSideDialogPositioned] = useState(false);

    const setSelectedBbox = useKnowledgeStore((state) => state.setSelectedBbox);

    useEffect(() => {
        // Clear selected highlight bbox when switching chunks
        setSelectedBbox([])
    }, [selectedChunkIndex])

    // Table configuration (keep original logic)
    const tableConfig = useMemo(() => ({
        file_ids: selectedFileId ? [selectedFileId] : [],
        unInitData: true
    }), [selectedFileId]);
    // 在 Paragraphs 组件中添加
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

            // 如果有传入的 fileId，确保 currentFile 被设置
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

    // 在组件初始化时调用
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

            // Fix: Parse chunk_bboxes and store boolean value for "is not empty"
            let chunkBboxes = [];
            try {
                const firstChunk = response.data?.[0];
                if (firstChunk?.metadata?.bbox) {

                    // First check if bbox is empty string
                    if (typeof firstChunk.metadata.bbox === 'string' && JSON.parse(firstChunk?.metadata?.bbox).chunk_bboxes === '') {
                        console.log('bbox is empty string');
                        chunkBboxes = [];
                    } else {
                        // Parse JSON
                        const bboxObj = JSON.parse(firstChunk.metadata.bbox);
                        chunkBboxes = bboxObj.chunk_bboxes || [];
                    }
                }
            } catch (e) {
                console.error('Failed to parse chunk_bboxes:', e);
                chunkBboxes = [];
            }

            // Store boolean value for "is not empty array" (not the original array)
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
        let chunkIndexPage = chunkIndex % pageSize;
        console.log('Converted localIndex:', chunkIndexPage);

        const bbox = { chunk_bboxes: selectedBbox };

        const bboxStr = selectedBbox.length ? JSON.stringify(bbox) : safeChunks[chunkIndexPage]?.bbox || '';
        captureAndAlertRequestErrorHoc(updateChunkApi({
            knowledge_id: Number(id),
            file_id: selectedFileId || currentFile?.id || '',
            chunk_index: chunkIndex,
            text,
            bbox: bboxStr
        }))
        setChunks(chunks => chunks.map(chunk =>
            chunk.chunkIndex === chunkIndex ? { ...chunk, bbox: bboxStr, text } : chunk
        ));

        refreshData(
            (item) => item?.metadata?.chunk_index === chunkIndex,
            (item) => ({ text, metadata: { ...item.metadata, bbox: bboxStr } })
        );
    }, [id, currentFile, refreshData, selectedBbox, safeChunks, pageSize, selectedFileId]);

    const fetchFileUrl = useCallback(async (fileId) => {
        console.log('Getting file URL:', fileId);
        if (!fileId) return '';

        try {
            setIsFetchingUrl(true);
            const res = await getFilePathApi(fileId);
            const pares = await getFileBboxApi(fileId);
            setPartitions(pares || []);

            // Get current selected file information
            const currentFile = rawFiles.find(f => String(f.id) === String(fileId));

            let finalUrl = '';
            let finalPreviewUrl = '';

            // Check if there are valid preview_url and original_url
            const hasPreviewUrl = typeof res.preview_url === 'string' && res.preview_url.trim() !== '';
            const hasOriginalUrl = typeof res.original_url === 'string' && res.original_url.trim() !== '';

            if (currentFile) {
                if (hasPreviewUrl) {
                    // Has preview_url → prioritize use
                    finalUrl = res.preview_url.trim();
                    finalPreviewUrl = res.preview_url.trim();
                } else {
                    // No preview_url → use original_url or alternative URL
                    finalUrl = hasOriginalUrl ? res.original_url.trim() : '';
                    finalPreviewUrl = finalUrl;
                }
                // }
            } else {
                // If current file not found, use default strategy
                finalUrl = hasPreviewUrl ? res.preview_url.trim() : (hasOriginalUrl ? res.original_url.trim() : '');
                finalPreviewUrl = finalUrl;
            }

            if (finalUrl) {
                finalUrl = decodeURIComponent(finalUrl);
                finalPreviewUrl = decodeURIComponent(finalPreviewUrl);
                // Update both state and ref (ref takes effect immediately)
                setFileUrl(finalUrl);
                setPreviewUrl(finalPreviewUrl);
                // Store original_url in ref
                latestOriginalUrlRef.current = hasOriginalUrl ? decodeURIComponent(res.original_url.trim()) : '';
                return finalUrl;
            } else {
                setFileUrl('');
                setPreviewUrl('');
                latestOriginalUrlRef.current = '';
                return '';
            }
        } catch (err) {
            console.error('Failed to get file URL:', err);
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
        // Check if current path is adjust page and doesn't have valid state data
        const pathName = location.pathname.replace(__APP_ENV__.BASE_URL, '')
        if (pathName.startsWith('/filelib/adjust/') && !window.history.state?.isAdjustMode) {
            // Extract ID (e.g., extract 2066 from /filelib/adjust/2066)
            const adjustId = pathName.split('/')[3];
            if (adjustId) {
                // Redirect to corresponding filelib page
                navigate(`/filelib/${adjustId}`, { replace: true });
            }
        }
    }, [location.pathname, navigate]);

    // Generate chunks from datalist (keep original logic)
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

        // Immediately update UI to avoid flickering
        // const selectedFile = rawFiles.find(f => String(f.id) === newFileId);
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
            // if (!selectedFile) throw new Error(t('file.fileNotFound'));

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

    // 初始化时设置默认选中的文件 ID
    useEffect(() => {
        if (fileId && !selectedFileId) {
            setSelectedFileId(String(fileId));
        }
    }, [fileId, selectedFileId]);

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

        if (!name) {
            setMetadataError(t('metadialog.nameRequired'));
            return;
        }

        if (name.length > 255) {
            setMetadataError(t('metadialog.nameTooLong'));
            return;
        }

        const nameRegex = /^[a-z][a-z0-9_]*$/;
        if (!nameRegex.test(name)) {
            setMetadataError(t('metadialog.nameInvalid'));
            return;
        }

        const exists = predefinedMetadata.some(item => item.name === name);
        if (exists) {
            setMetadataError(t('metadialog.nameExists'));
            return;
        }

        try {
            await addMetadata(Number(id), [{
                field_name: name,
                field_type: type.toLowerCase()
            }]);
            const knowledgeDetails = await getKnowledgeDetailApi([id]);
            const knowledgeDetail = knowledgeDetails[0];

            if (knowledgeDetail && knowledgeDetail.metadata_fields) {
                const formattedFields = Object.entries(knowledgeDetail.metadata_fields).map(([fieldName, fieldData]) => ({
                    id: `meta_${fieldName}`,
                    name: fieldData.field_name || fieldName,
                    type: fieldData.field_type.charAt(0).toUpperCase() + fieldData.field_type.slice(1),
                    updated: fieldData.updated_at
                }));
                setPredefinedMetadata(formattedFields);
            }
            setNewMetadata({ name: '', type: 'String' });
            setMetadataError('');

            setSideDialog({ type: 'search', open: true });

        } catch (error) {
            console.error("Failed to create metadata field:", error);
            setMetadataError(t('metadialog.nameReserved'));
        }
    }, [newMetadata, predefinedMetadata, t, id]);

    const handleSearchMetadataClick = useCallback(async () => {
        try {
            const knowledgeDetails = await getKnowledgeDetailApi([id]);
            const knowledgeDetail = knowledgeDetails[0];

            if (knowledgeDetail && knowledgeDetail.metadata_fields) {
                const formattedFields = Object.entries(knowledgeDetail.metadata_fields).map(([fieldName, fieldData]) => ({
                    id: `meta_${fieldName}`,
                    name: fieldData.field_name || fieldName,
                    type: fieldData.field_type.charAt(0).toUpperCase() + fieldData.field_type.slice(1),
                    updated: fieldData.updated_at
                }));
                setPredefinedMetadata(formattedFields);
            } else {
                setPredefinedMetadata([]);
            }
        } catch (error) {
            console.error("Failed to get knowledge base metadata fields:", error);
            setPredefinedMetadata([]);
        } finally {
            setMetadataError('');
            setSideDialog({ type: 'search', open: true });
        }
    }, [id, t]);

    const handleCreateMetadataClick = useCallback(() => {
        setNewMetadata({ name: '', type: 'String' });
        setMetadataError('');
        setSideDialog({ type: 'create', open: true });
    }, []);

    const closeSideDialog = useCallback(() => {
        setSideDialog({ type: null, open: false });
        setMetadataError('');
        setNewMetadata({ name: '', type: 'String' });
        setIsSideDialogPositioned(false);
    }, []);

    const handleAddFromSearch = useCallback((metadata) => {
        const exists = mainMetadataList.some(item => item.name === metadata.name);
        if (exists) {
            toast({ description: t('metadialog.alreadyExists') });
            return;
        }
        const newItem = {
            ...metadata,
            id: `temp_meta_${Date.now()}_${metadata.name}`,
            updated_at: Date.now(),
            value: ''
        };
        setMainMetadataList(prev => [...prev, newItem]);
        closeSideDialog();
    }, [closeSideDialog, mainMetadataList, t]);

    const handleMetadataClick = useCallback(async () => {
        if (currentFile?.fullData) {
            try {
                const res = await getMetaFile(currentFile.id);
                setFileInfor(res);
                const fetchedMetadata = res.user_metadata || [];
                const metadataArray = Object.entries(fetchedMetadata).map(([fieldName, fieldData]) => ({
                    id: `meta_${fieldName}`,
                    name: fieldData.field_name || fieldName,
                    type: fieldData.field_type ?
                        fieldData.field_type.charAt(0).toUpperCase() + fieldData.field_type.slice(1).toLowerCase() :
                        'String',
                    value: fieldData.field_value || '',
                    originalValue: fieldData.field_value || '',
                    updated_at: fieldData.updated_at || 0,
                }));
                const sortedMetadata = metadataArray.sort((a, b) => {
                    return (a.updated_at || 0) - (b.updated_at || 0);
                });

                setMainMetadataList(sortedMetadata);

                setMetadataDialog({
                    open: true,
                    file: currentFile.fullData
                });
            } catch (error) {
                console.error("Failed to get file metadata:", error);
                setMetadataDialog({
                    open: true,
                    file: currentFile.fullData
                });
            }
        }
    }, [currentFile]);

    // Adjust segmentation strategy
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

    // Parse segmentation strategy description (keep original logic)
    const splitRuleDesc = useCallback((file) => {
        if (!file.split_rule) return '';
        const suffix = file.file_name?.split('.').pop()?.toUpperCase() || '';
        try {
            const rule = JSON.parse(file.split_rule);
            const { excel_rule } = rule;

            // Process Excel file rules
            if (excel_rule && ['XLSX', 'XLS', 'CSV'].includes(suffix)) {
                return t('file.excelRule', { length: excel_rule.slice_length });
            }

            // Process separator rules
            const { separator, separator_rule } = rule;
            if (separator && separator_rule && separator.length === separator_rule.length) {
                const displayItems = separator.map((sep, index) => {
                    // Core fix: Convert actual newlines to visible \n string
                    const displaySep = sep
                        .replace(/\n/g, '\\n')  // Replace newline
                        .replace(/\r/g, '\\r')  // Replace carriage return (optional)
                        .replace(/\t/g, '\\t'); // Replace tab (optional)

                    // Add cutting symbol based on rule
                    const prefix = separator_rule[index] === 'before' ? '✂️' : '';
                    const suffix = separator_rule[index] === 'after' ? '✂️' : '';

                    return `${prefix}${displaySep}${suffix}`;
                });
                return displayItems.join(', ');
            }
        } catch (e) {
            console.error('Failed to parse segmentation strategy:', e);
        }

        // Fallback handling when parsing fails
        return file.split_rule
            .replace(/\n/g, '\\n')
            .replace(/\r/g, '\\r')
            .replace(/\t/g, '\\t');
    }, [t]);

    const handleDeleteChunk = useCallback(async (data) => {
        try {
            const updatedChunks = chunks.filter(chunk => chunk.chunkIndex !== data);
            setChunks(updatedChunks);

            if (selectedChunkIndex === data) {
                setSelectedBbox([]);
            }

            await captureAndAlertRequestErrorHoc(delChunkApi({
                knowledge_id: Number(id),
                file_id: selectedFileId || currentFile?.id || '',
                chunk_index: data || 0
            }));

            await new Promise(resolve => setTimeout(resolve, 100));

            await reload();

        } catch (error) {
            console.error('Failed to delete chunk:', error);
            await reload();
        }
    }, [
        id,
        reload,
        chunks,
        selectedFileId,
        currentFile?.id,
        selectedChunkIndex,
        setSelectedBbox,
        t
    ]);

    const formatFileSize = useCallback((bytes) => {
        if (bytes === 0) return '0 Bytes';

        // Define unit conversion boundaries (1024-based)
        const KB = 1024;
        const MB = KB * 1024;
        const GB = MB * 1024;

        // Select appropriate unit based on file size
        if (bytes < MB) {
            // Less than 1024KB (1MB), use KB
            return `${(bytes / KB).toFixed(2)} KB`;
        } else if (bytes < GB) {
            // Between 1024KB and 1024MB, use MB
            return `${(bytes / MB).toFixed(2)} MB`;
        } else {
            // 1024MB and above, use GB
            return `${(bytes / GB).toFixed(2)} GB`;
        }
    }, []);

    // Preview component rule configuration (keep original logic)
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

    // Preview display judgment (keep original logic)
    // const isExcelFile = currentFile && ['xlsx', 'xls', 'csv'].includes(currentFile.suffix?.toLowerCase());
    const isPreviewVisible =
        selectedFileId &&
        currentFile &&
        (previewUrl || fileUrl) && // Compatible with either previewUrl or fileUrl having value
        !isFetchingUrl;
    const isParagraphVisible = datalist.length > 0;

    // Layout class name calculation (keep original logic)
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

    const updateSideDialogPosition = useCallback(() => {
        if (!mainMetadataDialogRef.current || !sideDialog.open) return;

        const rect = mainMetadataDialogRef.current.getBoundingClientRect();
        const gap = isSmallScreen ? 0 : 4;
        let left = rect.right + gap;

        if (left + sideDialogWidth > screenWidth) {
            left = screenWidth - sideDialogWidth - 8;
        }

        const newPosition = {
            top: Math.max(rect.top, 8),
            left: Math.max(left, 8)
        };

        setSideDialogPosition(newPosition);
        setIsSideDialogPositioned(true);
    }, [mainMetadataDialogRef, sideDialog.open, isSmallScreen, screenWidth, sideDialogWidth]);

    useEffect(() => {
        const handleResize = () => {
            const newWidth = window.innerWidth;
            setScreenWidth(newWidth);
        };

        window.addEventListener("resize", handleResize);
        return () => window.removeEventListener("resize", handleResize);
    }, []);

    useEffect(() => {
        if (!metadataDialog.open || !sideDialog.open) {
            setIsSideDialogPositioned(false);
            return;
        }

        const timer1 = setTimeout(() => {
            updateSideDialogPosition();
        }, 0);

        const timer2 = setTimeout(() => {
            updateSideDialogPosition();
        }, 50);

        const timer3 = setTimeout(() => {
            updateSideDialogPosition();
        }, 100);

        return () => {
            clearTimeout(timer1);
            clearTimeout(timer2);
            clearTimeout(timer3);
        };
    }, [metadataDialog.open, sideDialog.open, updateSideDialogPosition]);

    const handleWriteableChange = (writable: boolean) => {
        setIsKnowledgeAdmin(writable);
    }

    const handleSaveUserMetadata = useCallback(async () => {
        const knowledge_id = selectedFileId
        const user_metadata_list = mainMetadataList.map(item => {
            if (!item.id.startsWith('temp_') && item.updated_at !== undefined) {
                return {
                    field_name: item.name,
                    field_value: item.value || '',
                    updated_at: item.updated_at,
                };
            }
            return {
                field_name: item.name,
                field_value: item.value || '',
                updated_at: item.updated_at || Math.floor(Date.now() / 1000),
            };
        });
        try {
            await saveUserMetadataApi(knowledge_id, user_metadata_list);

            toast({
                title: t('common.success'),
                description: t('metadialog.saveSuccess'),
            });
            setMetadataDialog(prev => ({ ...prev, open: false }));
            setMetadataError('');
        } catch (error) {
            toast({
                variant: 'error',
                description: error,
            });
            console.error('Failed to save metadata:', error);
            setMetadataError(t('metadialog.saveFailed'));
        }
    }, [mainMetadataList, selectedFileId, t]);

    return (
        <div className="relative flex flex-col h-[calc(100vh-64px)]">
            {load && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,1)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}
            {/* Top navigation bar */}
            <div className="flex justify-between items-center px-4 pt-4 pb-4">
                <div className="min-w-72 max-w-[440px] flex items-center gap-2">
                    <ShadTooltip content={t('common.back')} side="top">
                        <button
                            className="extra-side-bar-buttons w-[36px] max-h-[36px]"
                            onClick={onBack}
                        >
                            <ArrowLeft className="side-bar-button-size" />
                        </button>
                    </ShadTooltip>
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
                        <SearchInput
                            placeholder={t('segment.searchSegments')}
                            onChange={(e) => search(e.target.value)}
                            disabled={!selectedFileId}
                        />
                    </div>
                    <Button variant="outline" onClick={handleMetadataClick} className="px-4 whitespace-nowrap">
                        <ClipboardPenLine size={16} strokeWidth={1.5} className="mr-1" />
                        {t('metadialog.title')}
                    </Button>
                    <Tip content={!isEditable && t('common.noPermission')} side='top'>
                        <Button
                            disabled={!isEditable}
                            onClick={handleAdjustSegmentation}
                            className={`px-4 whitespace-nowrap disabled:pointer-events-auto`}>
                            {t('segment.adjustStrategy')}
                        </Button>
                    </Tip>
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
                        rules={previewRules}
                        edit
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
                                edit={isEditable}
                                page={page}
                                className="h-[calc(100vh-206px)] pb-6"
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
                            <FileText className="size-8 mb-3 opacity-50" />
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