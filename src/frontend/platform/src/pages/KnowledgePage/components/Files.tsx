import { Link, useNavigate, useParams } from "react-router-dom";
import { Button } from "../../../components/bs-ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";

import { FileIcon } from "@/components/bs-icons/file";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import Tip from "@/components/bs-ui/tooltip/tip";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { downloadFile, truncateString } from "@/util/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@radix-ui/react-dropdown-menu";
import { CircleAlertIcon, ClipboardPenLine, Filter, RotateCw, Trash2, Download } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { deleteFile, getKnowledgeDetailApi, readFileByLibDatabase, retryKnowledgeFileApi, batchDownloadFileApi } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import useKnowledgeStore from "../useKnowledgeStore";
import { MetadataManagementDialog } from "./MetadataManagementDialog";

interface StatusIndicatorProps {
    status: number;
    remark?: string;
}
// 1. 定义状态配置映射表
const STATUS_CONFIG: Record<number, { labelKey: string; colorClass: string; bgClass: string }> = {
    1: { labelKey: "parsing", colorClass: "text-[#4D9BF0]", bgClass: "bg-[#4D9BF0]" },
    2: { labelKey: "completed", colorClass: "text-green-500", bgClass: "bg-green-500" },
    3: { labelKey: "parseFailed", colorClass: "text-red-500", bgClass: "bg-red-500" },
    4: { labelKey: "parsing", colorClass: "text-[#4D9BF0]", bgClass: "bg-[#4D9BF0]" },
    5: { labelKey: "queuing", colorClass: "text-yellow-500", bgClass: "bg-yellow-500" },
    6: { labelKey: "timeout", colorClass: "text-red-500", bgClass: "bg-red-500" },
};

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({ status, remark }) => {
    const { t } = useTranslation()
    const config = STATUS_CONFIG[status];
    const reason = useMemo(() => {
        if (remark?.indexOf('{') === 0) {
            try {
                const obj = JSON.parse(remark)
                return t(`errors.${obj.status_code}`, obj.data)
            } catch (error) {
                return remark
            }
        }
        return remark
    }, [remark, t])

    // 如果状态不在定义中，返回 null 或默认 UI
    if (!config) return null;

    const renderTooltip = () => {
        let tooltipContent = "";

        if (status === 3 && remark) {
            tooltipContent = reason; // 解析失败的报错原因
        } else if (status === 6) {
            tooltipContent = t('timeoutTip', { ns: 'knowledge' })
        }

        if (!tooltipContent) return null;

        return (
            <TooltipProvider delayDuration={100}>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <CircleAlertIcon size={16} className="cursor-pointer" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="whitespace-pre-line">
                        <div className="max-w-96 text-left break-all whitespace-normal">
                            {tooltipContent}
                        </div>
                    </TooltipContent>
                </Tooltip>
            </TooltipProvider>
        );
    };

    const BadgeContent = (
        <div className="flex items-center gap-2 cursor-default">
            <span className={`size-[6px] rounded-full ${config?.bgClass}`}></span>
            <span className={`font-[500] text-[14px] leading-[100%] text-center flex gap-0.5 items-center ${config?.colorClass}`}>
                {t(config?.labelKey, { ns: 'knowledge' })}
                {(status === 3 || status === 6) && renderTooltip()}
            </span>
        </div>
    );

    // 其他状态直接渲染内容
    return BadgeContent;
};

export default function Files({ onPreview }) {
    const { t } = useTranslation('knowledge')
    const { id } = useParams()
    const { toast } = useToast()

    const { isEditable, setEditable } = useKnowledgeStore();
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData } = useTable({ cancelLoadingWhenReload: true }, (param) =>
        readFileByLibDatabase({ ...param, id, name: param.keyword }).then(res => {
            setEditable(res.writeable)
            return res
        })
    )
    const [metadataOpen, setMetadataOpen] = useState(false);
    const navigate = useNavigate()

    // Store complete file objects (preserving all original parameters)
    const [selectedFileObjs, setSelectedFileObjs] = useState<Array<Record<string, any>>>([]);
    const [isAllSelected, setIsAllSelected] = useState(false);

    const [selectedFilters, setSelectedFilters] = useState<number[]>([]);
    const [tempFilters, setTempFilters] = useState<number[]>([]);
    const [isFilterOpen, setIsFilterOpen] = useState(false);
    const [metadataFields, setMetadataFields] = useState<Array<{ field_name: string; field_type: string }>>([]);
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
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteFile'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFile(id).then(res => {
                    reload()
                    setSelectedFileObjs(prev => prev.filter(file => file.id !== id));
                }))
                next()
            },
        })
    }

    // Retry parsing (preserving original file parameter structure)
    const handleRetry = (files) => {
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi({ file_objs: files }).then(res => {
            reload()
        }))
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
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteSelectedFiles', { count: selectedFileObjs.length }),
            onOk(next) {
                captureAndAlertRequestErrorHoc(Promise.all(
                    selectedFileObjs.map(file => deleteFile(file.id))
                ).then(() => {
                    setPage(1);
                    reload();
                    setSelectedFileObjs([]);
                    setIsAllSelected(false);
                }))
                next();
            },
        })
    }

    // Batch Download
    const [isDownloading, setIsDownloading] = useState(false);
    const handleBatchDownload = async () => {
        setIsDownloading(true);
        try {
            const fileIds = selectedFileObjs.map(f => Number(f.id));
            if (!fileIds.length) {
                toast({ variant: 'error', description: t('selectFile', { ns: 'knowledge' }) });
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
                toast({ variant: 'error', description: t('errors.10003', { ns: 'bs' }) });
            }
        } catch (e) {
            toast({ variant: 'error', description: t('errors.10003', { ns: 'bs' }) });
        } finally {
            setIsDownloading(false);
        }
    };

    // Batch retry
    const handleBatchRetry = () => {
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
            if (el.file_name.includes('xlsx', 'xls', 'csv') && el.parse_type !== "local" && el.parse_type !== "uns") {
                const excel_rule = JSON.parse(el.split_rule).excel_rule
                return {
                    ...el,
                    strategy: ['', t('everyRowsAsOneSegment', { count: excel_rule?.slice_length })]
                }
            }
            if (!el.split_rule) return {
                ...el,
                strategy: ['', '']
            }
            const rule = JSON.parse(el.split_rule)
            const { separator, separator_rule } = rule
            const data = separator.map((el, i) => `${separator_rule[i] === 'before' ? '✂️' : ''}${el}${separator_rule[i] === 'after' ? '✂️' : ''}`)
            return {
                ...el,
                strategy: [data.length > 2 ? data.slice(0, 2).join(',') : '', data.join(',')]
            }
        })
    }, [datalist, t])

    const splitRuleDesc = (el) => {
        if (!el.split_rule) return el.strategy[1].replace(/\n/g, '\\n')
        const suffix = el.file_name.split('.').pop().toUpperCase()
        const excel_rule = JSON.parse(el.split_rule).excel_rule
        if (!excel_rule) return el.strategy[1].replace(/\n/g, '\\n')
        return ['XLSX', 'XLS', 'CSV'].includes(suffix) ? t('everyRowsAsOneSegment', { count: excel_rule.slice_length }) : el.strategy[1].replace(/\n/g, '\\n')
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
                    <LoadingIcon />
                </div>
            )}

            {/* Top action bar combined */}
            <div className="absolute right-0 top-[-62px] flex flex-wrap md:flex-nowrap justify-end gap-2 md:gap-4 items-center z-10 max-w-[calc(100vw-40px)] bg-background md:bg-transparent p-1 md:p-0 rounded-lg">

                {/* Batch Actions */}
                {selectedFileObjs.length > 0 && (
                    <div className="flex items-center gap-2 mr-1 md:mr-0 pr-2 md:pr-4 border-r border-gray-200 dark:border-gray-700">
                        <Button
                            variant="outline"
                            onClick={handleBatchDownload}
                            disabled={isDownloading}
                            className="flex items-center gap-1 disabled:pointer-events-auto h-9 px-2 sm:px-4"
                        >
                            {isDownloading ? <LoadingIcon className="h-4 w-4 mr-1" /> : <Download size={16} />}
                            <span className="hidden sm:inline">{t('download', { ns: 'bs' })}</span>
                        </Button>
                        <Tip content={!isEditable && t('noOperationPermission')} side='bottom'>
                            <Button
                                variant="outline"
                                onClick={handleBatchDelete}
                                disabled={!isEditable}
                                className="flex items-center gap-1 disabled:pointer-events-auto h-9 px-2 sm:px-4"
                            >
                                <Trash2 size={16} />
                                <span className="hidden sm:inline">{t('delete')}</span>
                            </Button>
                        </Tip>
                        {hasSelectedFailedFiles && (
                            <Tip content={!isEditable && t('noOperationPermission')} side='bottom'>
                                <Button
                                    variant="outline"
                                    onClick={handleBatchRetry}
                                    disabled={!isEditable}
                                    className="flex items-center gap-1 disabled:pointer-events-auto h-9 px-2 sm:px-4"
                                >
                                    <RotateCw size={16} />
                                    <span className="hidden sm:inline">{t('retry')}</span>
                                </Button>
                            </Tip>
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
                    <Button
                        variant="outline"
                        onClick={() => setMetadataOpen(true)}
                        className="px-2 md:px-4 whitespace-nowrap h-9"
                    >
                        <ClipboardPenLine size={16} strokeWidth={1.5} className="mr-0 md:mr-1" />
                        <span className="hidden md:inline">{t('metaData')}</span>
                    </Button>
                    {isEditable && (
                        <Link to={`/filelib/upload/${id}`}>
                            <Button className="px-4 md:px-8 h-9">{t('uploadFile')}</Button>
                        </Link>
                    )}
                </div>
            </div>

            <div className="h-[calc(100vh-180px)] overflow-y-auto pb-20">
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
                            <TableHead className="min-w-[100px]">{t('updateTime')}</TableHead>
                            <TableHead className="flex items-center gap-4 min-w-[130px]">
                                {t('status')}
                                <div className="relative">
                                    <DropdownMenu open={isFilterOpen} onOpenChange={handleOpenChange}>
                                        <DropdownMenuTrigger asChild>
                                            <Button
                                                variant="ghost"
                                                className={`flex items-center gap-1 ${selectedFilters.length > 0 ? 'text-blue-500' : ''}`}
                                            >
                                                <Filter size={16} />
                                            </Button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent
                                            className="h-full p-0 shadow-lg rounded-md border"
                                            style={{
                                                backgroundColor: 'white',
                                                opacity: 1,
                                            }}
                                            align="end"
                                        >
                                            <div className="px-2">
                                                {[
                                                    {
                                                        value: 2,
                                                        label: 'Completed',
                                                        color: 'text-green-500',
                                                        icon: (
                                                            <div className="flex items-center gap-2 mt-2">
                                                                <span className="size-[6px] rounded-full bg-green-500"></span>
                                                                <span className="font-[500] text-[14px] text-green-500 leading-[100%]">
                                                                    {t("completed")}
                                                                </span>
                                                            </div>
                                                        )
                                                    },
                                                    {
                                                        value: 1,
                                                        label: 'Parsing',
                                                        color: 'text-[#4D9BF0]',
                                                        icon: (
                                                            <div className="flex items-center gap-2 mt-2">
                                                                <span className="size-[6px] rounded-full bg-[#4D9BF0]"></span>
                                                                <span className="font-[500] text-[14px] text-[#4D9BF0] leading-[100%]">
                                                                    {t("parsing")}
                                                                </span>
                                                            </div>
                                                        )
                                                    },
                                                    {
                                                        value: 3,
                                                        label: 'Parse Failed',
                                                        color: 'text-red-500',
                                                        icon: (
                                                            <div className="flex items-center gap-2 mt-2">
                                                                <span className="size-[6px] rounded-full bg-red-500"></span>
                                                                <span className="font-[500] text-[14px] text-red-500 leading-[100%]">
                                                                    {t("parseFailed")}
                                                                </span>
                                                            </div>
                                                        )
                                                    }
                                                ].map(({ value, label, color, icon }) => (
                                                    <div
                                                        key={value}
                                                        className="flex items-center gap-3 px-2 py-1.5 hover:bg-gray-100 rounded cursor-pointer"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            setTempFilters(prev =>
                                                                prev.includes(value)
                                                                    ? prev.filter(v => v !== value)
                                                                    : [...prev, value]
                                                            );
                                                        }}
                                                    >
                                                        <input
                                                            type="checkbox"
                                                            checked={tempFilters.includes(value)}
                                                            onChange={() => { }}
                                                            className="h-4 w-4 mt-2 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                                        />
                                                        <div className="flex items-center gap-2">
                                                            {icon}
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                            <div className="border-t border-gray-200"></div>
                                            <div className="flex justify-around gap-2 px-3 py-2">
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        resetFilters()
                                                    }}
                                                    disabled={tempFilters.length === 0}
                                                >
                                                    {t("reset")}
                                                </Button>
                                                <Button
                                                    size="sm"
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        applyFilters()
                                                    }}
                                                >
                                                    {t("confirm")}
                                                </Button>
                                            </div>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </div>
                            </TableHead>
                            <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {dataSouce.map(el => (
                            <TableRow
                                key={el.id}
                                onClick={() => {
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
                                    <Tip content={el.file_name} align="start" >
                                        <div className="flex items-center gap-2">
                                            <FileIcon
                                                type={el.file_name.split('.').pop().toLowerCase() || 'txt'}
                                                className="size-[30px] min-w-[30px]"
                                            />
                                            {truncateString(el.file_name, 35)}
                                        </div>
                                    </Tip>
                                </TableCell>
                                <TableCell>
                                    {el.strategy[0] ? (
                                        <TooltipProvider delayDuration={100}>
                                            <Tooltip>
                                                <TooltipTrigger className="truncate max-w-[106px]">{el.strategy[1].replace(/\n/g, '\\n')}</TooltipTrigger>
                                                <TooltipContent>
                                                    <div className="max-w-96 text-left break-all whitespace-normal">{el.strategy[1].replace(/\n/g, '\\n')}</div>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    ) : splitRuleDesc(el)}
                                </TableCell>
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>

                                <TableCell>
                                    <StatusIndicator status={el.status} remark={el.remark} />
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-1">
                                        {el.status === 3 && (
                                            <Tip content={!isEditable && t('noOperationPermission')} side='top'>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    disabled={!isEditable}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleRetry([el]); // Single retry passes complete object
                                                    }}
                                                    className="disabled:pointer-events-auto"
                                                    title={t('retry')}
                                                >
                                                    <RotateCw size={16} />
                                                </Button>
                                            </Tip>
                                        )}
                                        <Tip
                                            content={!isEditable && t('noOperationPermission')}
                                            side='top'
                                            styleClasses="-translate-x-6"
                                        >
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="disabled:pointer-events-auto"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDelete(el.id);
                                                }}
                                                disabled={!isEditable}
                                                title={t('delete')}
                                            >
                                                <Trash2 size={16} />
                                            </Button>
                                        </Tip>
                                    </div>
                                </TableCell>
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
                hasManagePermission={isEditable}
                id={id}
                initialMetadata={metadataFields}
            />
        </div>

    )
}