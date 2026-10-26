// @ts-strict-ignore
import { Button, SearchInput, notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";
import { useNavigate,useParams,useSearchParams } from "react-router-dom";

import {
Table,
TableBody,
TableCell,
TableHead,
TableHeader,
TableRow
} from "../../../components/bs-ui/table";
import { FileStatusFilter } from "./FileStatusFilter";
import { StatusIndicator } from "./KnowledgeFileStatus";
import { KnowledgeTooltip } from "./KnowledgeTooltip";
export { StatusIndicator } from "./KnowledgeFileStatus";

import { FileIcon } from "@/components/bs-icons/file";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Checkbox } from "@bisheng/ui";


import { downloadFile,truncateString } from "@/util/utils";

import { locationContext } from "@/contexts/locationContext";
import { useContext,useEffect,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";

import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { batchDownloadFileApi,deleteFile,getKnowledgeDetailApi,readFileByLibDatabase,retryKnowledgeFileApi } from "../../../controllers/API";
import { showApiError } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import { knowledgeUploadCapabilities } from "../knowledgeUploadCapabilities";
import useKnowledgeStore from "../useKnowledgeStore";
import AddKnowledgeFileMenu from "./AddKnowledgeFileMenu";
import { MetadataManagementDialog } from "./MetadataManagementDialog";
import WebLinkImportDialog from "./WebLinkImportDialog";
import FileTagList from "./tags/FileTagList";
import KnowledgeTagSelect from "./tags/KnowledgeTagSelect";

function normalizeWebLinkDisplayName(fileName: string): string {
    const trimmed = fileName.trim().replace(/\.md$/i, "").trim();
    if (!trimmed) return fileName;
    return trimmed.toLowerCase().endsWith(".html") ? trimmed : `${trimmed}.html`;
}

function getKnowledgeFileDisplayName(file: Record<string, any>): string {
    const fileName = String(file.file_name ?? "");
    return file.file_source === "web_link" ? normalizeWebLinkDisplayName(fileName) : fileName;
}

export default function Files({ onPreview, canEditKb = false, canDeleteKb = false }) {
    const { appConfig } = useContext(locationContext);
    const { t } = useTranslation('knowledge')
    const { id } = useParams()
    const [searchParams] = useSearchParams()


    const { setEditable } = useKnowledgeStore();
    const initialAbnormalFilter = searchParams.get('fileStatus') === 'abnormal'
    const initialStatusFilters = initialAbnormalFilter ? [3, 6, 7] : []
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData } = useTable(
        {
            cancelLoadingWhenReload: true,
            ...(initialAbnormalFilter ? { status: initialStatusFilters } : {}),
        },
        (param) => readFileByLibDatabase({ ...param, id, name: param.keyword })
    )
    const [metadataOpen, setMetadataOpen] = useState(false);
    const [webLinkOpen, setWebLinkOpen] = useState(false);
    const navigate = useNavigate()

    // Store complete file objects (preserving all original parameters)
    const [selectedFileObjs, setSelectedFileObjs] = useState<Array<Record<string, any>>>([]);
    const [isAllSelected, setIsAllSelected] = useState(false);

    const [selectedFilters, setSelectedFilters] = useState<number[]>(initialStatusFilters);
    const [tempFilters, setTempFilters] = useState<number[]>(initialStatusFilters);
    const [isFilterOpen, setIsFilterOpen] = useState(false);
    const [metadataFields, setMetadataFields] = useState<Array<{ field_name: string; field_type: string }>>([]);
    useEffect(() => {
        setEditable(canEditKb);
    }, [canEditKb, setEditable]);

    // Polling during parsing
    const timerRef = useRef(null)
    useEffect(() => {
        if (datalist.some(el => el.status === 1)) {
            timerRef.current = setTimeout(() => {
                reload()
            }, 5000)
            return () => clearTimeout(timerRef.current)
        }
    }, [datalist])

    const applyFilters = () => {
        setSelectedFilters([...tempFilters]);
        const params: any = {};
        if (tempFilters.length > 0) {
            params.status = tempFilters;
        } else {
            params.status = [];
        }

        filterData(params);
        setIsFilterOpen(false);
        setSelectedFileObjs([]);
        setIsAllSelected(false);
    };

    const resetFilters = () => {
        const emptyFilters: number[] = [];
        setTempFilters(emptyFilters);
        setSelectedFilters(emptyFilters);
        filterData({ status: [] });
        setIsFilterOpen(false);
        setSelectedFileObjs([]);
        setIsAllSelected(false);
    };

    const handleDelete = (id) => {
        if (!canDeleteKb) return;
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteFile'),
            onOk(next) {
                return deleteFile(id).then(() => {
                    reload()
                    setSelectedFileObjs(prev => prev.filter(file => file.id !== id));
                    next()
                })
            },
        })
    }

    // Retry parsing (preserving original file parameter structure)
    const handleRetry = (files) => {
        if (!canEditKb) return;
        retryKnowledgeFileApi({ file_objs: files }).then(() => {
            reload()
        }).catch(showApiError)
    }

    // Select all/Deselect all (storing complete file objects)
    const toggleSelectAll = (checked: boolean) => {
        if (checked) {
            // Select all current page and deduplicate
            const newFiles = datalist
                .filter(file => !selectedFileObjs.some(item => item.id === file.id))
                .map(file => ({ ...file })); // Deep copy to preserve all parameters
            setSelectedFileObjs([...selectedFileObjs, ...newFiles]);
        } else {
            // Deselect all current page
            const currentPageIds = new Set(datalist.map(file => file.id));
            setSelectedFileObjs(prev => prev.filter(file => !currentPageIds.has(file.id)));
        }
        setIsAllSelected(checked);
    };

    // Single file selection/deselection
    const toggleSelectFile = (file: Record<string, any>, checked: boolean) => {
        if (checked) {
            // Avoid duplicate additions
            if (!selectedFileObjs.some(item => item.id === file.id)) {
                setSelectedFileObjs([...selectedFileObjs, { ...file }]);
            }
        } else {
            setSelectedFileObjs(prev => prev.filter(item => item.id !== file.id));
            setIsAllSelected(false);
        }
    };

    // Check if current page is fully selected
    const isCurrentPageAllSelected = useMemo(() => {
        if (datalist.length === 0) return false;
        const selectedIds = new Set(selectedFileObjs.map(file => file.id));
        return datalist.every(file => selectedIds.has(file.id));
    }, [datalist, selectedFileObjs]);

    // Batch delete
    const handleBatchDelete = () => {
        if (!canDeleteKb) return;
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteSelectedFiles', { count: selectedFileObjs.length }),
            onOk(next) {
                return Promise.all(
                    selectedFileObjs.map(file => deleteFile(file.id))
                ).then(() => {
                    setPage(1);
                    reload();
                    setSelectedFileObjs([]);
                    setIsAllSelected(false);
                    next();
                })
            },
        })
    }

    // Batch Download
    const [isDownloading, setIsDownloading] = useState(false);
    const canBatchEditTags = canEditKb && selectedFileObjs.length > 0 && selectedFileObjs.every(file => file.status === 2);
    const hasRowActions = canEditKb || canDeleteKb;
    const handleBatchDownload = async () => {
        setIsDownloading(true);
        try {
            const fileIds = selectedFileObjs.map(f => Number(f.id));
            if (!fileIds.length) {
                notification.open({ type: 'error', description: String(t('selectFile', { ns: 'knowledge' }) ?? '') });
                setIsDownloading(false);
                return;
            }
            const url = await batchDownloadFileApi({ knowledge_id: Number(id), file_ids: fileIds });
            if (url) {
                if (fileIds.length === 1) {
                    downloadFile(url, selectedFileObjs[0].file_name);
                } else {
                    const now = new Date();
                    const dateStr =
                        String(now.getFullYear()) +
                        String(now.getMonth() + 1).padStart(2, '0') +
                        String(now.getDate()).padStart(2, '0');
                    const timeStr = String(now.getHours()).padStart(2, '0') + String(now.getMinutes()).padStart(2, '0');
                    const libName = localStorage.getItem('libname') || '知识库';
                    downloadFile(url, `${libName}_${dateStr}_${timeStr}.zip`);
                }
            } else {
                notification.open({ type: 'error', description: String(t('api_errors:10003') ?? '') });
            }
        } catch (e) {
            notification.open({ type: 'error', description: String(t('api_errors:10003') ?? '') });
        } finally {
            setIsDownloading(false);
        }
    };

    // Batch retry
    const handleBatchRetry = () => {
        if (!canEditKb) return;
        // Filter failed files, preserving complete parameters
        const failedFiles = selectedFileObjs.filter(file => file.status === 3);

        if (failedFiles.length > 0) {
            handleRetry(failedFiles); // Directly pass complete file object array
            setSelectedFileObjs([]);
            setIsAllSelected(false);
        }
    }

    // Strategy parsing
    const dataSouce = useMemo(() => {
        return datalist.map(el => {
            const suffix = el.file_name.split('.').pop()?.toLowerCase() || '';
            const displayFileName = getKnowledgeFileDisplayName(el);
            if (['xlsx', 'xls', 'csv', 'et'].includes(suffix) && el.parse_type !== "local" && el.parse_type !== "uns") {
                const excel_rule = JSON.parse(el.split_rule).excel_rule
                return {
                    ...el,
                    display_file_name: displayFileName,
                    strategy: ['', t('everyRowsAsOneSegment', { count: excel_rule?.slice_length })]
                }
            }
            if (!el.split_rule) return {
                ...el,
                display_file_name: displayFileName,
                strategy: ['', '']
            }
            const rule = JSON.parse(el.split_rule)
            const { separator, separator_rule } = rule
            const data = separator.map((el, i) => `${separator_rule[i] === 'before' ? '✂️' : ''}${el}${separator_rule[i] === 'after' ? '✂️' : ''}`)
            return {
                ...el,
                display_file_name: displayFileName,
                strategy: [data.length > 2 ? data.slice(0, 2).join(',') : '', data.join(',')]
            }
        })
    }, [datalist, t])

    const splitRuleDesc = (el) => {
        if (!el.split_rule) return el.strategy[1].replace(/\n/g, '\\n')
        const suffix = el.file_name.split('.').pop().toUpperCase()
        const excel_rule = JSON.parse(el.split_rule).excel_rule
        if (!excel_rule) return el.strategy[1].replace(/\n/g, '\\n')
        return ['XLSX', 'XLS', 'CSV', 'ET'].includes(suffix) ? t('everyRowsAsOneSegment', { count: excel_rule.slice_length }) : el.strategy[1].replace(/\n/g, '\\n')
    }

    // Check if there are selected parsing failed files
    const hasSelectedFailedFiles = useMemo(() => {
        return selectedFileObjs.some(file => file.status === 3);
    }, [selectedFileObjs]);

    useEffect(() => {
        if (isFilterOpen) {
            setTempFilters([...selectedFilters]);
        }
    }, [isFilterOpen, selectedFilters]);

    // Update select all status when page data changes
    useEffect(() => {
        setIsAllSelected(datalist.length > 0 && datalist.every(file =>
            selectedFileObjs.some(item => item.id === file.id)
        ));
    }, [datalist, selectedFileObjs]);

    // Handle dropdown menu close event
    const handleOpenChange = (open: boolean) => {
        if (!open && isFilterOpen) {
            applyFilters();
        }
        setIsFilterOpen(open);
    };

    useEffect(() => {
        // Load metadata when dialog opens and knowledge base ID exists
        if (metadataOpen && id) { // Note: dependency is metadataOpen, not open
            const fetchMetadata = async () => {
                try {
                    // Call API to get knowledge base details
                    const knowledgeDetails = await getKnowledgeDetailApi([id]);
                    const knowledgeDetail = knowledgeDetails[0]; // Get first knowledge base details
                    if (knowledgeDetail && knowledgeDetail.metadata_fields) {
                        setMetadataFields(knowledgeDetail.metadata_fields);
                    } else {
                        setMetadataFields([]); // Set to empty array if no metadata
                    }

                } catch (err: any) {
                    console.error("Metadata loading failed:", err);
                    // Can add user prompt here
                }
            };
            fetchMetadata();
        } else if (!metadataOpen) {
            // Clear metadata state when dialog closes
            setMetadataFields([]);
        }
    }, [metadataOpen, id]);

    return (
        <div className="relative">

            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <Outlined.Loading  className="size-4 animate-spin"/>
                </div>
            )}

            {/* Top action bar combined */}
            <div className="absolute right-0 top-[-62px] flex flex-wrap md:flex-nowrap justify-end gap-2 md:gap-4 items-center z-10 max-w-[calc(100vw-40px)] bg-background md:bg-transparent p-1 md:p-0 rounded-lg">

                {/* Batch Actions */}
                {selectedFileObjs.length > 0 && (
                    <div className="flex items-center gap-2 mr-1 md:mr-0 pr-2 md:pr-4 border-r border-gray-200 dark:border-gray-700">
                        <Button variant="outlined" onClick={handleBatchDownload} disabled={isDownloading} className="flex items-center gap-1 disabled:pointer-events-auto sm:px-4" color="default">
                            {isDownloading ? <Outlined.Loading className="animate-spin h-4 w-4 mr-1" /> : <Outlined.Download size={16} />}
                            <span className="hidden sm:inline">{t('download', { ns: 'bs' })}</span>
                        </Button>
                        {canEditKb && (
                            <KnowledgeTooltip content={!canBatchEditTags ? t('tagOperationRequiresCompletedFiles') : ''} side='bottom'>
                            <KnowledgeTagSelect
                                knowledgeId={id}
                                fileIds={selectedFileObjs.map(f => Number(f.id))}
                                onUpdate={reload}
                                isEditable={canBatchEditTags}
                                mode="batch"
                            >
                                <Button variant="outlined" disabled={!canBatchEditTags} className="flex items-center gap-1 disabled:pointer-events-auto sm:px-4" onClick={(e) => e.stopPropagation()} color="default">
                                    <Outlined.Tag size={16} />
                                    <span className="hidden sm:inline">{t('tags')}</span>
                                </Button>
                            </KnowledgeTagSelect>
                            </KnowledgeTooltip>
                        )}
                        {canDeleteKb && (
                            <Button variant="outlined" onClick={handleBatchDelete} className="flex items-center gap-1 disabled:pointer-events-auto sm:px-4" color="default">
                                <Outlined.Delete size={16} />
                                <span className="hidden sm:inline">{t('delete')}</span>
                            </Button>
                        )}
                        {canEditKb && hasSelectedFailedFiles && (
                                <Button variant="outlined" onClick={handleBatchRetry} className="flex items-center gap-1 disabled:pointer-events-auto sm:px-4" color="default">
                                    <Outlined.Refresh size={16} />
                                    <span className="hidden sm:inline">{t('retry')}</span>
                                </Button>
                        )}
                    </div>
                )}

                {/* Regular actions */}
                <div className="flex items-center gap-2 md:gap-4">
                    <SearchInput placeholder={t('searchFileName')} onChange={(e) => {
                        search(e.target.value);
                        setSelectedFileObjs([]);
                        setIsAllSelected(false);
                    }} />
                    {canEditKb && (
                        <Button variant="outlined" onClick={() => setMetadataOpen(true)} className="md:px-4 whitespace-nowrap" color="default">
                            <Outlined.FileEditing size={16} strokeWidth={1.5} className="mr-0 md:mr-1" />
                            <span className="hidden md:inline">{t('metaData')}</span>
                        </Button>
                    )}
                    {canEditKb && (
                        <AddKnowledgeFileMenu
                            buttonClassName="px-4 md:px-8"
                            supportedFormatsLabel={t(
                                appConfig.enableMediaUpload
                                    ? "supportedFormatsTip"
                                    : "supportedFormatsTipWithoutMedia",
                                { defaultValue: "" },
                            )}
                            onUploadFile={() => navigate(`/filelib/upload/${id}`)}
                            onWebLink={() => {
                                if (knowledgeUploadCapabilities.webLink) {
                                    setWebLinkOpen(true);
                                }
                            }}
                        />
                    )}
                </div>
            </div>

            <div className="h-[calc(100vh-180px-var(--license-banner-h,0px))] overflow-y-auto pb-20">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="min-w-[10px]">
                                <Checkbox
                                    checked={isCurrentPageAllSelected}
                                    onCheckedChange={toggleSelectAll}
                                />
                            </TableHead>
                            <TableHead className="min-w-[250px]">{t('fileName')}</TableHead>
                            <TableHead>{t('segmentationStrategy')}</TableHead>
                            <TableHead className="min-w-[150px]">{t('tags')}</TableHead>
                            <TableHead className="min-w-[100px]">{t('updateTime')}</TableHead>
                            <TableHead className="flex items-center gap-4 min-w-[130px]">
                                {t('status')}
                                <div className="relative">
                                    <FileStatusFilter open={isFilterOpen} onOpenChange={handleOpenChange}
                                        selected={selectedFilters} draft={tempFilters} onDraftChange={setTempFilters}
                                        onApply={applyFilters} onReset={resetFilters} />
                                </div>
                            </TableHead>
                            {hasRowActions && (
                                <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                            )}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {dataSouce.map(el => (
                            <TableRow
                                key={el.id}
                                onClick={() => {
                                    if (document.body.dataset.knowledgeTagDialogOpen === 'true') {
                                        return;
                                    }
                                    if (selectedFileObjs.length === 0 && el.status !== 3 && el.status !== 1) {
                                        onPreview(el.id);
                                    }
                                }}
                                className={selectedFileObjs.some(file => file.id === el.id) ? 'bg-blue-50' : ''}
                            >
                                <TableCell>
                                    <Checkbox
                                        checked={selectedFileObjs.some(file => file.id === el.id)}
                                        onCheckedChange={(checked) => {
                                            toggleSelectFile(el, checked as boolean);
                                        }}
                                        onClick={(e) => e.stopPropagation()}
                                    />
                                </TableCell>
                                <TableCell className="min-w-[250px]">
                                    <KnowledgeTooltip content={el.display_file_name || el.file_name} align="start" >
                                        <div className="flex items-center gap-2">
                                            <FileIcon
                                                type={(el.display_file_name || el.file_name).split('.').pop().toLowerCase() || 'txt'}
                                                className="size-[30px] min-w-[30px]"
                                            />
                                            {truncateString(el.display_file_name || el.file_name, 35)}
                                        </div>
                                    </KnowledgeTooltip>
                                </TableCell>
                                <TableCell>
                                    {el.strategy[0] ? (
                                        <KnowledgeTooltip content={<><div className="max-w-96 text-left break-all whitespace-normal">{el.strategy[1].replace(/\n/g, '\\n')}</div></>}>
<button type="button">{el.strategy[1].replace(/\n/g, '\\n')}</button>
</KnowledgeTooltip>
                                    ) : splitRuleDesc(el)}
                                </TableCell>
                                <TableCell className="min-w-[150px]">
                                    <FileTagList
                                        knowledgeId={id}
                                        fileId={el.id}
                                        tags={el.tags || []}
                                        isEditable={canEditKb && el.status === 2}
                                        onUpdate={reload}
                                    />
                                </TableCell>
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>

                                <TableCell>
                                    <StatusIndicator status={el.status} remark={el.remark} />
                                </TableCell>
                                {hasRowActions && <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-1">
                                        {canEditKb && el.status === 3 && (
                                                <Button variant="text" size="medium" onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleRetry([el]); // Single retry passes complete object
                                                    }} className="disabled:pointer-events-auto" title={t('retry')} color="default" iconOnly>
                                                    <Outlined.Refresh size={16} />
                                                </Button>
                                        )}
                                        {canDeleteKb && (
                                            <Button variant="text" size="medium" className="disabled:pointer-events-auto" onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDelete(el.id);
                                                }} title={t('delete')} color="default" iconOnly>
                                                <Outlined.Delete size={16} />
                                            </Button>
                                        )}
                                    </div>
                                </TableCell>}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            <div className="bisheng-table-footer px-6">
                <p></p>
                <div>
                    <AutoPagination
                        page={page}
                        pageSize={pageSize}
                        total={total}
                        showTotal={true}
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>
            <MetadataManagementDialog
                open={metadataOpen}
                onOpenChange={() => setMetadataOpen(false)}
                onSave={() => { }}
                hasManagePermission={canEditKb}
                id={id}
                initialMetadata={metadataFields}
            />
            {knowledgeUploadCapabilities.webLink && (
                <WebLinkImportDialog
                    knowledgeId={id}
                    open={webLinkOpen}
                    onOpenChange={setWebLinkOpen}
                    onImported={reload}
                />
            )}
        </div>

    )
}
