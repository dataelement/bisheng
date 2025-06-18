import { Link, useParams } from "react-router-dom";
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
import { Filter, RotateCw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "../../../components/bs-ui/select";
import { deleteFile, readFileByLibDatabase, retryKnowledgeFileApi } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import { LoadingIcon } from "@/components/bs-icons/loading";
import useKnowledgeStore from "../useKnowledgeStore";
import { truncateString } from "@/util/utils";

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

    // filter
    const [filter, setFilter] = useState(999)
    useEffect(() => {
        filterData({ status: filter })
    }, [filter])


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

    const selectChange = (id) => {
        setFilter(Number(id))
    }

    // 重试解析
    const handleRetry = (objs) => {
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi({ file_objs: objs }).then(res => {
            reload()
        }))
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

    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="absolute right-0 top-[-62px] flex gap-4 items-center">
            <SearchInput placeholder={t('searchFileName')} onChange={(e) => search(e.target.value)}></SearchInput>
            {isEditable && <Link to={`/filelib/upload/${id}`}><Button className="px-8" onClick={() => { }}>{t('uploadFile')}</Button></Link>}
        </div>
        <div className="h-[calc(100vh-144px)] overflow-y-auto pb-20">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="min-w-[300px]">{t('fileName')}</TableHead>
                        <TableHead className="min-w-[220px]">文件摘要</TableHead>
                        <TableHead className="flex items-center gap-4 min-w-[130px]">
                            {t('status')}
                            <Select onValueChange={selectChange}>
                                <SelectTrigger className="border-none w-16">
                                    <Filter size={16} className={`cursor-pointer ${filter === 999 ? '' : 'text-gray-950'}`} />
                                </SelectTrigger>
                                <SelectContent className="w-fit">
                                    <SelectGroup>
                                        <SelectItem value={'999'}>{t('all')}</SelectItem>
                                        <SelectItem value={'1'}>{t('parsing')}</SelectItem>
                                        <SelectItem value={'2'}>{t('completed')}</SelectItem>
                                        <SelectItem value={'3'}>{t('parseFailed')}</SelectItem>
                                    </SelectGroup>
                                </SelectContent>
                            </Select>
                        </TableHead>
                        <TableHead className="min-w-[100px]">{t('uploadTime')}</TableHead>
                        <TableHead>切分策略</TableHead>
                        <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {dataSouce.map(el => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium">{truncateString(el.file_name, 35)}</TableCell>
                            <TableCell className="font-medium">
                                {el.title?.length > 20 ? <TooltipProvider delayDuration={100}>
                                    <Tooltip>
                                        <TooltipTrigger>{el.title.slice(0, 20)}...</TooltipTrigger>
                                        <TooltipContent>
                                            <div className="max-w-96 text-left break-all whitespace-normal">{el.title}</div>
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider> : el.title}
                            </TableCell>
                            <TableCell>
                                {el.status === 3 ? <div className="flex items-center">
                                    <TooltipProvider delayDuration={100}>
                                        <Tooltip>
                                            <TooltipTrigger>
                                                <span className='text-red-500'>{t('parseFailed')}</span>
                                            </TooltipTrigger>
                                            <TooltipContent>
                                                <div className="max-w-96 text-left break-all whitespace-normal">{el.remark}</div>
                                            </TooltipContent>
                                        </Tooltip>
                                    </TooltipProvider>
                                    <Button variant="link"><RotateCw size={16} onClick={() => handleRetry([el])} /></Button>
                                </div> :
                                    <span className={el.status === 3 && 'text-red-500'}>
                                        {[t('parseFailed'), t('parsing'), t('completed'), t('parseFailed')][el.status]}
                                    </span>
                                }
                            </TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell>
                                {el.strategy[0] ? <TooltipProvider delayDuration={100}>
                                    <Tooltip>
                                        <TooltipTrigger>{el.strategy[0]}...</TooltipTrigger>
                                        <TooltipContent>
                                            <div className="max-w-96 text-left break-all whitespace-normal">{el.strategy[1].replace(/\n/g, '\\n')}</div>
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider> : splitRuleDesc(el)}
                            </TableCell>
                            <TableCell className="text-right">
                                <Button variant="link" disabled={el.status !== 2} className="px-2 dark:disabled:opacity-80" onClick={() => onPreview(el.id)}>{t('view')}</Button>
                                {isEditable ?
                                    <Button variant="link" onClick={() => handleDelete(el.id)} className="text-red-500 px-2">{t('delete')}</Button> :
                                    <Button variant="link" className="ml-4 text-gray-400 px-2">{t('delete')}</Button>
                                }
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

};
