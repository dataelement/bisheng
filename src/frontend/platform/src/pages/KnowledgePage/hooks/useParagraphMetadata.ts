import { notification } from '@bisheng/ui';

import { addMetadata,getKnowledgeDetailApi,getMetaFile,saveUserMetadataApi } from '@/controllers/API'
import type { TFunction } from 'i18next'
import { useCallback,useEffect,useRef,useState } from 'react'
import type { FileInfo,MetadataItem,NewMetadata } from '../components/metadataTypes'

type MetadataDefinition = { field_name?: string; field_type: string; updated_at?: number; field_value?: string }
interface ParagraphMetadataProps {
    id?: string
    selectedFileId: string
    currentFile: { id: string | number; fullData?: FileInfo } | null
    canEditKb: boolean
    t: TFunction
    notify: typeof notification.open
}

export function useParagraphMetadata({ id, selectedFileId, currentFile, canEditKb, t, notify }: ParagraphMetadataProps) {
    const [metadataDialog, setMetadataDialog] = useState<{ open: boolean; file: FileInfo | null }>({
        open: false,
        file: null
    });
    const [mainMetadataList, setMainMetadataList] = useState<MetadataItem[]>([]);
    const [newMetadata, setNewMetadata] = useState<NewMetadata>({
        name: '',
        type: 'String'
    });
    const [metadataError, setMetadataError] = useState('');
    const [sideDialog, setSideDialog] = useState<{ type: 'search' | 'create' | null; open: boolean }>({
        type: null,
        open: false
    });
    const [predefinedMetadata, setPredefinedMetadata] = useState<MetadataItem[]>([]);
    const [searchTerm, setSearchTerm] = useState("");
    const [fileInfor, setFileInfor] = useState<FileInfo>();


    const mainMetadataDialogRef = useRef<HTMLDivElement>(null);
    const [sideDialogPosition, setSideDialogPosition] = useState({ top: 0, left: 0 });
    const [screenWidth, setScreenWidth] = useState(window.innerWidth);
    const isSmallScreen = screenWidth < 1366;
    const sideDialogWidth = isSmallScreen ? 240 : 300;
    const [isSideDialogPositioned, setIsSideDialogPositioned] = useState(false);


    const handleDeleteMainMetadata = useCallback((id: string) => {
        setMainMetadataList(prev => prev.filter(item => item.id !== id));
    }, []);

    const handleMainMetadataValueChange = useCallback((id: string, value: string) => {
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
                const formattedFields = Object.entries(knowledgeDetail.metadata_fields as Record<string, MetadataDefinition>).map(([fieldName, fieldData]) => ({
                    id: `meta_${fieldName}`,
                    name: fieldData.field_name || fieldName,
                    type: (fieldData.field_type.charAt(0).toUpperCase() + fieldData.field_type.slice(1)) as MetadataItem['type'],
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
                const formattedFields = Object.entries(knowledgeDetail.metadata_fields as Record<string, MetadataDefinition>).map(([fieldName, fieldData]) => ({
                    id: `meta_${fieldName}`,
                    name: fieldData.field_name || fieldName,
                    type: (fieldData.field_type.charAt(0).toUpperCase() + fieldData.field_type.slice(1)) as MetadataItem['type'],
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
    }, [id]);

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

    const handleAddFromSearch = useCallback((metadata: MetadataItem) => {
        const exists = mainMetadataList.some(item => item.name === metadata.name);
        if (exists) {
            notify({ description: t('metadialog.alreadyExists') });
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
    }, [closeSideDialog, mainMetadataList, t, notify]);

    const handleMetadataClick = useCallback(async () => {
        if (!canEditKb) return;
        if (currentFile?.fullData) {
            try {
                const res = await getMetaFile(currentFile.id);
                setFileInfor(res);
                const fetchedMetadata = res.user_metadata || [];
                const metadataArray = Object.entries(fetchedMetadata as Record<string, MetadataDefinition>).map(([fieldName, fieldData]) => ({
                    id: `meta_${fieldName}`,
                    name: fieldData.field_name || fieldName,
                    type: (fieldData.field_type ?
                        fieldData.field_type.charAt(0).toUpperCase() + fieldData.field_type.slice(1).toLowerCase() :
                        'String') as MetadataItem['type'],
                    value: fieldData.field_value || '',
                    originalValue: fieldData.field_value || '',
                    updated_at: fieldData.updated_at || 0,
                }));
                const sortedMetadata = metadataArray.sort((a, b) => {
                    return Number(a.updated_at || 0) - Number(b.updated_at || 0);
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
    }, [canEditKb, currentFile]);


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


    const handleSaveUserMetadata = useCallback(async () => {
        if (!canEditKb) return;
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

            notify({
                title: t('common.success'),
                description: t('metadialog.saveSuccess'),
            });
            setMetadataDialog(prev => ({ ...prev, open: false }));
            setMetadataError('');
        } catch (error) {
            notify({
                type: 'error',
                description: error instanceof Error ? error.message : String(error),
            });
            console.error('Failed to save metadata:', error);
            setMetadataError(t('metadialog.saveFailed'));
        }
    }, [canEditKb, mainMetadataList, selectedFileId, t, notify]);



    const splitRuleDesc = useCallback((file: { split_rule?: string; file_name?: string }) => {
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
                const displayItems = separator.map((sep: string, index: number) => {
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


    const formatFileSize = useCallback((bytes: number) => {
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

    return { metadataDialog, setMetadataDialog, mainMetadataList, newMetadata, setNewMetadata, metadataError, setMetadataError, sideDialog, setSideDialog, predefinedMetadata, searchTerm, setSearchTerm, fileInfor, mainMetadataDialogRef, sideDialogPosition, isSmallScreen, sideDialogWidth, isSideDialogPositioned, handleDeleteMainMetadata, handleMainMetadataValueChange, handleSaveNewMetadata, handleSearchMetadataClick, handleCreateMetadataClick, closeSideDialog, handleAddFromSearch, handleMetadataClick, handleSaveUserMetadata, splitRuleDesc, formatFileSize }
}
