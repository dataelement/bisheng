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
import { truncateString } from "@/util/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@radix-ui/react-dropdown-menu";
import { ClipboardPenLine, Filter, RotateCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { deleteFile, getKnowledgeDetailApi, readFileByLibDatabase, retryKnowledgeFileApi } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import useKnowledgeStore from "../useKnowledgeStore";
import Tip from "@/components/bs-ui/tooltip/tip";
import { MetadataManagementDialog } from "./MetadataManagementDialog";

export default function Files({ onPreview }) {
    const { t } = useTranslation('knowledge')
    const { id } = useParams()

    const { isEditable, setEditable } = useKnowledgeStore();
    const [dialogOpen, setDialogOpen] = useState(false)
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

            {/* Top action bar */}
            {selectedFileObjs.length > 0 && (
                <div className="absolute top-[-62px] left-0 right-0 flex justify-center items-center p-2 border-b z-10">
                    <div className="flex items-center">
                        <div className="flex gap-2">
                            <Tip content={!isEditable && 'No operation permission'} side='bottom'>
                                <Button
                                    variant="outline"
                                    onClick={handleBatchDelete}
                                    disabled={!isEditable}
                                    className="flex items-center gap-1 disabled:pointer-events-auto"
                                >
                                    <Trash2 size={16} />
                                    {t('delete')}
                                </Button>
                            </Tip>
                            {hasSelectedFailedFiles && (
                                <Tip content={!isEditable && 'No operation permission'} side='bottom'>
                                    <Button
                                        variant="outline"
                                        onClick={handleBatchRetry}
                                        disabled={!isEditable}
                                        className="flex items-center gap-1 disabled:pointer-events-auto"
                                    >
                                        <RotateCw size={16} />
                                        {t('retry')}
                                    </Button>
                                </Tip>
                            )}
                        </div>
                    </div>
                </div>
            )}

            <div className="absolute right-0 top-[-62px] flex gap-4 items-center z-999">
                <SearchInput placeholder={t('searchFileName')} onChange={(e) => {
                    search(e.target.value);
                    setSelectedFileObjs([]);
                    setIsAllSelected(false);
                }} />
                <Button
                    variant="outline"
                    onClick={() => setMetadataOpen(true)}
                    className="px-4 whitespace-nowrap"
                >
                    <ClipboardPenLine size={16} strokeWidth={1.5} className="mr-1"/>
                    {t('metaData')}
                </Button>
                {isEditable && (
                    <Link to={`/filelib/upload/${id}`}>
                        <Button className="px-8">{t('uploadFile')}</Button>
                    </Link>
                )}
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
                                    <div className="flex items-center gap-2">
                                        <FileIcon
                                            type={el.file_name.split('.').pop().toLowerCase() || 'txt'}
                                            className="size-[30px] min-w-[30px]"
                                        />
                                        {truncateString(el.file_name, 35)}
                                    </div>
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
                                    {el.status === 3 ? (

                                        <div className="flex items-center">
                                            <TooltipProvider delayDuration={100}>
                                                <Tooltip>
                                                    <TooltipTrigger className="flex items-center gap-2">
                                                        <span className="size-[6px] rounded-full bg-red-500"></span>
                                                        <span className="font-[500] text-[14px] text-red-500 leading-[100%] text-center">
                                                            {t("parseFailed")}
                                                        </span>
                                                    </TooltipTrigger>

                                                    <TooltipContent side="top" className="whitespace-pre-line">
                                                        <div className="max-w-96 text-left break-all whitespace-normal">{el.remark}</div>
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                        </div>
                                    ) : (
                                        <div className="flex items-center gap-2">
                                            {el.status === 2 ? (
                                                <Tooltip>
                                                    <TooltipTrigger className="flex items-center gap-2">
                                                        <span className="size-[6px] rounded-full bg-green-500"></span>
                                                        <span className="font-[500] text-[14px] text-green-500 leading-[100%] text-center">
                                                            {t("completed")}
                                                        </span>
                                                    </TooltipTrigger>
                                                </Tooltip>
                                            ) : el.status === 1 || el.status === 4 ? (
                                                <Tooltip>
                                                    <TooltipTrigger className="flex items-center gap-2">
                                                        <span className="size-[6px] rounded-full bg-[#4D9BF0]"></span>
                                                        <span className="font-[500] text-[14px] text-[#4D9BF0] leading-[100%] text-center">
                                                            {t("parsing")}
                                                        </span>
                                                    </TooltipTrigger>
                                                </Tooltip>
                                            ) : null}
                                        </div>
                                    )}
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-1">
                                        {el.status === 3 && (
                                            <Tip content={!isEditable && 'No operation permission'} side='top'>
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
                                            content={!isEditable && 'No operation permission'}
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
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>
            <MetadataManagementDialog
                open={metadataOpen} 
                onOpenChange={() => setMetadataOpen(false)}
                onSave={() => {}}
                hasManagePermission={isEditable}
                id={id}
                initialMetadata={metadataFields}
            />
        </div>
        
    )
}