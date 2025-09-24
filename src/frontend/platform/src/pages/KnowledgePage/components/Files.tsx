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
import { Filter, RotateCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { deleteFile, readFileByLibDatabase, retryKnowledgeFileApi } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import useKnowledgeStore from "../useKnowledgeStore";
import Tip from "@/components/bs-ui/tooltip/tip";

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

    // 存储完整文件对象（保留所有原始参数）
    const [selectedFileObjs, setSelectedFileObjs] = useState<Array<Record<string, any>>>([]);
    const [isAllSelected, setIsAllSelected] = useState(false);

    // 其他原有状态
    const [selectedFilters, setSelectedFilters] = useState<number[]>([]);
    const [tempFilters, setTempFilters] = useState<number[]>([]);
    const [isFilterOpen, setIsFilterOpen] = useState(false);

    // 解析中轮巡
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

    // 重试解析（保留原始文件参数结构）
    const handleRetry = (files) => {
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi({ file_objs: files }).then(res => {
            reload()
        }))
    }

    // 全选/取消全选（存储完整文件对象）
    const toggleSelectAll = (checked: boolean) => {
        if (checked) {
            // 全选当前页并去重
            const newFiles = datalist
                .filter(file => !selectedFileObjs.some(item => item.id === file.id))
                .map(file => ({ ...file })); // 深拷贝保留所有参数
            setSelectedFileObjs([...selectedFileObjs, ...newFiles]);
        } else {
            // 取消全选当前页
            const currentPageIds = new Set(datalist.map(file => file.id));
            setSelectedFileObjs(prev => prev.filter(file => !currentPageIds.has(file.id)));
        }
        setIsAllSelected(checked);
    };

    // 单个文件选中/取消选中
    const toggleSelectFile = (file: Record<string, any>, checked: boolean) => {
        if (checked) {
            // 避免重复添加
            if (!selectedFileObjs.some(item => item.id === file.id)) {
                setSelectedFileObjs([...selectedFileObjs, { ...file }]);
            }
        } else {
            setSelectedFileObjs(prev => prev.filter(item => item.id !== file.id));
            setIsAllSelected(false);
        }
    };

    // 检查当前页是否全部选中
    const isCurrentPageAllSelected = useMemo(() => {
        if (datalist.length === 0) return false;
        const selectedIds = new Set(selectedFileObjs.map(file => file.id));
        return datalist.every(file => selectedIds.has(file.id));
    }, [datalist, selectedFileObjs]);

    // 批量删除
    const handleBatchDelete = () => {
        bsConfirm({
            title: t('prompt'),
            desc: t('确认删除选中文件', { count: selectedFileObjs.length }),
            onOk(next) {
                captureAndAlertRequestErrorHoc(Promise.all(
                    selectedFileObjs.map(file => deleteFile(file.id))
                ).then(() => {
                    reload();
                    setSelectedFileObjs([]);
                    setIsAllSelected(false);
                }))
                next();
            },
        })
    }

    // 批量重试（核心修复：传递完整文件对象）
    const handleBatchRetry = () => {
        // 筛选失败文件，保留完整参数
        const failedFiles = selectedFileObjs.filter(file => file.status === 3);

        if (failedFiles.length > 0) {
            handleRetry(failedFiles); // 直接传递完整文件对象数组
            setSelectedFileObjs([]);
            setIsAllSelected(false);
        }
    }

    // 策略解析（原有逻辑不变）
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
        if (!el.split_rule) return el.strategy[1].replace(/\n/g, '\\n')
        const suffix = el.file_name.split('.').pop().toUpperCase()
        const excel_rule = JSON.parse(el.split_rule).excel_rule
        if (!excel_rule) return el.strategy[1].replace(/\n/g, '\\n')
        return ['XLSX', 'XLS', 'CSV'].includes(suffix) ? `每 ${excel_rule.slice_length} 行作为一个分段` : el.strategy[1].replace(/\n/g, '\\n')
    }

    // 检查是否有选中的解析失败文件
    const hasSelectedFailedFiles = useMemo(() => {
        return selectedFileObjs.some(file => file.status === 3);
    }, [selectedFileObjs]);

    useEffect(() => {
        if (isFilterOpen) {
            setTempFilters([...selectedFilters]);
        }
    }, [isFilterOpen, selectedFilters]);

    // 页面数据变化时更新全选状态
    useEffect(() => {
        setIsAllSelected(datalist.length > 0 && datalist.every(file =>
            selectedFileObjs.some(item => item.id === file.id)
        ));
    }, [datalist, selectedFileObjs]);

    // 处理下拉菜单关闭事件
    const handleOpenChange = (open: boolean) => {
        if (!open && isFilterOpen) {
            applyFilters();
        }
        setIsFilterOpen(open);
    };

    return (
        <div className="relative">
            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
            )}

            {/* 顶部操作栏 */}
            {selectedFileObjs.length > 0 && (
                <div className="absolute top-[-62px] left-0 right-0 flex justify-center items-center p-2 border-b z-10">
                    <div className="flex items-center">
                        <div className="flex gap-2">
                            <Tip content={!isEditable && '暂无操作权限'} side='bottom'>
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
                                <Tip content={!isEditable && '暂无操作权限'} side='bottom'>
                                    <Button
                                        variant="outline"
                                        onClick={handleBatchRetry}
                                        disabled={!isEditable}
                                        className="flex items-center gap-1 disabled:pointer-events-auto"
                                    >
                                        <RotateCw size={16} />
                                        {t('重试')}
                                    </Button>
                                </Tip>
                            )}
                        </div>
                    </div>
                </div>
            )}

            <div className="absolute right-0 top-[-62px] flex gap-4 items-center z-20">
                <SearchInput placeholder={t('searchFileName')} onChange={(e) => {
                    search(e.target.value);
                    setSelectedFileObjs([]);
                    setIsAllSelected(false);
                }} />
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
                            <TableHead>切分策略</TableHead>
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
                                                        label: '已完成',
                                                        color: 'text-green-500',
                                                        icon: (
                                                            <div className="flex items-center gap-2 mt-2">
                                                                <span className="size-[6px] rounded-full bg-green-500"></span>
                                                                <span className="font-[500] text-[14px] text-green-500 leading-[100%]">
                                                                    已完成
                                                                </span>
                                                            </div>
                                                        )
                                                    },
                                                    {
                                                        value: 1,
                                                        label: '解析中',
                                                        color: 'text-[#4D9BF0]',
                                                        icon: (
                                                            <div className="flex items-center gap-2 mt-2">
                                                                <span className="size-[6px] rounded-full bg-[#4D9BF0]"></span>
                                                                <span className="font-[500] text-[14px] text-[#4D9BF0] leading-[100%]">
                                                                    解析中
                                                                </span>
                                                            </div>
                                                        )
                                                    },
                                                    {
                                                        value: 3,
                                                        label: '解析失败',
                                                        color: 'text-red-500',
                                                        icon: (
                                                            <div className="flex items-center gap-2 mt-2">
                                                                <span className="size-[6px] rounded-full bg-red-500"></span>
                                                                <span className="font-[500] text-[14px] text-red-500 leading-[100%]">
                                                                    解析失败
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
                                                            解析失败
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
                                                            已完成
                                                        </span>
                                                    </TooltipTrigger>
                                                </Tooltip>
                                            ) : el.status === 1 || el.status === 4 ? (
                                                <Tooltip>
                                                    <TooltipTrigger className="flex items-center gap-2">
                                                        <span className="size-[6px] rounded-full bg-[#4D9BF0]"></span>
                                                        <span className="font-[500] text-[14px] text-[#4D9BF0] leading-[100%] text-center">
                                                            解析中
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
                                            <Tip content={!isEditable && '暂无操作权限'} side='top'>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    disabled={!isEditable}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleRetry([el]); // 单个重试传递完整对象
                                                    }}
                                                    className="disabled:pointer-events-auto"
                                                    title={t('重试')}
                                                >
                                                    <RotateCw size={16} />
                                                </Button>
                                            </Tip>
                                        )}
                                        <Tip
                                            content={!isEditable && '暂无操作权限'}
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
        </div>
    )
}