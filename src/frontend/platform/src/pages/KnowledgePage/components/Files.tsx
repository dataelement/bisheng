import { Link, useParams, useNavigate } from "react-router-dom";
import { Button } from "../../../components/bs-ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { Check, Dot, Filter, RotateCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { deleteFile, readFileByLibDatabase, retryKnowledgeFileApi } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import { LoadingIcon } from "@/components/bs-icons/loading";
import useKnowledgeStore from "../useKnowledgeStore";
import { truncateString } from "@/util/utils";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Checkbox } from "@/components/bs-ui/checkbox";
import { FileIcon } from "@/components/bs-icons/file";
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@radix-ui/react-dropdown-menu";

export default function Files({ onPreview }) {
    const { t } = useTranslation('knowledge')
    const { id } = useParams()

    const { isEditable, setEditable } = useKnowledgeStore();
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData } = useTable({ cancelLoadingWhenReload: true }, (param) =>
        readFileByLibDatabase({ ...param, id, name: param.keyword }).then(res => {
            setEditable(res.writeable)
            return res
        })
    )
    const navigate = useNavigate()

    // 新增状态
    const [selectedFilters, setSelectedFilters] = useState<number[]>([]);
    const [tempFilters, setTempFilters] = useState<number[]>([]);
    const [isFilterOpen, setIsFilterOpen] = useState(false);
    const [renameModalOpen, setRenameModalOpen] = useState(false);
    const [currentFile, setCurrentFile] = useState(null);
    const [newFileName, setNewFileName] = useState('');
    const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());

    // 解析中 轮巡
    const timerRef = useRef(null)
    useEffect(() => {
        if (datalist.some(el => el.status === 1)) {
            timerRef.current = setTimeout(() => {
                reload()
            }, 5000)
            return () => clearTimeout(timerRef.current)
        }
    }, [datalist])

    // 筛选处理函数
    const handleFilterChange = (value: number) => {
        setTempFilters(prev =>
            prev.includes(value)
                ? prev.filter(v => v !== value)
                : [...prev, value]
        );
    };

    const applyFilters = () => {
        setSelectedFilters([...tempFilters]);
        // 确保传递正确的筛选参数格式
        filterData({ status: tempFilters.length > 0 ? tempFilters.join(',') : undefined });
        setIsFilterOpen(false);
    };

    const resetFilters = () => {
        const emptyFilters: number[] = [];
        setTempFilters(emptyFilters);
        setSelectedFilters(emptyFilters);
        filterData({ status: undefined });
        setIsFilterOpen(false);
    };

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteFile'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFile(id).then(res => {
                    reload()
                }))
                next()
            },
        })
    }

    // 重试解析
    const handleRetry = (objs) => {
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi({ file_objs: objs }).then(res => {
            reload()
        }))
    }

    // 全选/取消全选
    const toggleSelectAll = (checked: boolean) => {
        if (checked) {
            setSelectedFiles(new Set(datalist.map(file => file.id)));
        } else {
            setSelectedFiles(new Set());
        }
    };

    // 单个文件选中/取消选中
    const toggleSelectFile = (fileId: string, checked: boolean) => {
        const newSelectedFiles = new Set(selectedFiles);
        if (checked) {
            newSelectedFiles.add(fileId);
        } else {
            newSelectedFiles.delete(fileId);
        }
        setSelectedFiles(newSelectedFiles);
    };

    // 获取选中的文件
    const getSelectedFiles = () => {
        return datalist.filter(file => selectedFiles.has(file.id));
    };

    // 批量删除
    const handleBatchDelete = () => {
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteSelectedFiles', { count: selectedFiles.size }),
            onOk(next) {
                captureAndAlertRequestErrorHoc(Promise.all(
                    Array.from(selectedFiles).map(id => deleteFile(id))
                ).then(() => {
                    reload();
                    setSelectedFiles(new Set());
                }))
                next();
            },
        })
    }

    // 批量重试
    const handleBatchRetry = () => {
        const failedFiles = getSelectedFiles().filter(file => file.status === 3);
        if (failedFiles.length > 0) {
            handleRetry(failedFiles.map(file => file.id));
            setSelectedFiles(new Set());
        }
    }

    // 策略解析
    const dataSouce = useMemo(() => {
        return datalist.map(el => {
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
    }, [datalist])

    const splitRuleDesc = (el) => {
        if (!el.split_rule) return el.strategy[1].replace(/\n/g, '\\n') // 兼容历史数据
        const suffix = el.file_name.split('.').pop().toUpperCase()
        const excel_rule = JSON.parse(el.split_rule).excel_rule
        if (!excel_rule) return el.strategy[1].replace(/\n/g, '\\n') // 兼容历史数据
        return ['XLSX', 'XLS', 'CSV'].includes(suffix) ? `每 ${excel_rule.slice_length} 行作为一个分段` : el.strategy[1].replace(/\n/g, '\\n')
    }

    // 检查是否有选中的解析失败文件
    const hasSelectedFailedFiles = useMemo(() => {
        return getSelectedFiles().some(file => file.status === 3);
    }, [selectedFiles, datalist]);
    useEffect(() => {
        if (isFilterOpen) {
            setTempFilters([...selectedFilters]);
        }
    }, [isFilterOpen, selectedFilters]);
    return (
        <div className="relative">
            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
            )}

            {/* 顶部操作栏 */}
            {selectedFiles.size > 0 && (
                <div className="absolute top-[-62px] left-0 right-0 flex justify-center items-center p-2 border-b z-10">
                    <div className="flex gap-4 items-center">
                        {/* 批量操作按钮组 */}
                        {selectedFiles.size > 0 && (
                            <div className="flex">
                                <Button
                                    variant="outline"
                                    onClick={handleBatchDelete}
                                    className="flex items-center gap-1"
                                >
                                    <Trash2 size={16} />
                                    {t('delete')}
                                </Button>
                                {hasSelectedFailedFiles && (
                                    <Button
                                        variant="outline"
                                        onClick={handleBatchRetry}
                                        className="flex items-center gap-1"
                                    >
                                        <RotateCw size={16} />
                                        {t('重试')}
                                    </Button>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            )}

            <div className="absolute right-0 top-[-62px] flex gap-4 items-center">
                <SearchInput placeholder={t('searchFileName')} onChange={(e) => search(e.target.value)} />
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
                            <TableHead className="min-w-[50px]">
                                <Checkbox
                                    checked={selectedFiles.size === datalist.length && datalist.length > 0}
                                    onCheckedChange={toggleSelectAll}
                                />
                            </TableHead>
                            <TableHead className="min-w-[250px]">{t('fileName')}</TableHead>
                            <TableHead className="min-w-[100px]">{t('uploadTime')}</TableHead>
                            <TableHead>切分策略</TableHead>
                            <TableHead className="flex items-center gap-4 min-w-[130px]">
                                {t('status')}
                                <div className="relative">
                                    <DropdownMenu open={isFilterOpen} onOpenChange={setIsFilterOpen}>
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
                                                        label: '已完成',
                                                        color: 'text-blue-500',
                                                        icon: <img src="/success.svg" className="w-16 h-8" alt="已完成" />
                                                    },
                                                    {
                                                        value: 1,
                                                        label: '解析中',
                                                        color: 'text-green-500',
                                                        icon: <img src="/analysis.svg" className="w-16 h-8" alt="解析中" />
                                                    },
                                                    {
                                                        value: 3,
                                                        label: '解析失败',
                                                        color: 'text-red-500',
                                                        icon: <img src="/failed.svg" className="w-16 h-8" alt="解析失败" />
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
                                                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                                        />
                                                        <div className="flex items-center gap-2">
                                                            {icon}
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                            <div className="border-t border-gray-200"></div>
                                            <div className="flex justify-end gap-2 px-3 py-2">
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        resetFilters()
                                                    }}
                                                    disabled={tempFilters.length === 0}
                                                >
                                                    重置
                                                </Button>
                                                <Button
                                                    size="sm"
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        applyFilters()
                                                    }}
                                                >
                                                    确认
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
                                    if (!selectedFiles.size) {
                                        onPreview(el.id);
                                    }
                                }}
                                className={selectedFiles.has(el.id) ? 'bg-blue-50' : ''}
                            >
                                <TableCell>
                                    <Checkbox
                                        checked={selectedFiles.has(el.id)}
                                        onCheckedChange={(checked) => {
                                            toggleSelectFile(el.id, checked as boolean);
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
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                <TableCell>
                                    {el.strategy[0] ? (
                                        <TooltipProvider delayDuration={100}>
                                            <Tooltip>
                                                <TooltipTrigger>{el.strategy[0]}...</TooltipTrigger>
                                                <TooltipContent>
                                                    <div className="max-w-96 text-left break-all whitespace-normal">{el.strategy[1].replace(/\n/g, '\\n')}</div>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    ) : splitRuleDesc(el)}
                                </TableCell>
                                <TableCell>
                                    {el.status === 3 ? (
                                        <div className="flex items-center">
                                            <TooltipProvider delayDuration={100}>
                                                <Tooltip>
                                                    <TooltipTrigger className="flex items-center gap-2">
                                                        <img src="/failed.svg" className="w-16 h-8" alt="解析失败" />
                                                    </TooltipTrigger>
                                                    <TooltipContent>
                                                        <div className="max-w-96 text-left break-all whitespace-normal">{el.remark}</div>
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                        </div>
                                    ) : (
                                        <div className="flex items-center gap-2">
                                            {el.status === 2 ? (
                                                <img src="/success.svg" className="w-16 h-8" alt="已完成" />
                                            ) : el.status === 1 ? (
                                                <img src="/analysis.svg" className="w-16 h-8" alt="解析中" />
                                            ) : (
                                                <img src="/failed.svg" className="w-16 h-8" alt="解析失败" />
                                            )}
                                        </div>
                                    )}
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-2">
                                        {el.status === 3 && (
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleRetry([el.id]);
                                                }}
                                                title={t('重试')}
                                            >
                                                <RotateCw size={16} />
                                            </Button>
                                        )}
                                        {isEditable ? (
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleDelete(el.id);
                                                }}
                                                title={t('delete')}
                                            >
                                                <Trash2 size={16} />
                                            </Button>
                                        ) : (
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="text-gray-400 cursor-not-allowed"
                                                title={t('delete')}
                                                disabled
                                            >
                                                <Trash2 size={16} />
                                            </Button>
                                        )}
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
        </div>
    )
}