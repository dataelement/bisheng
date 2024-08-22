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

import { Filter, RotateCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
// import PaginationComponent from "../../components/PaginationComponent";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "../../../components/bs-ui/select";
import { deleteFile, readFileByLibDatabase } from "../../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";

export default function Files(params) {
    const { t } = useTranslation()
    const { id } = useParams()

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData, refreshData } = useTable({}, (param) =>
        readFileByLibDatabase({ ...param, id, name: param.keyword }).then(res => {
            setHasPermission(res.writeable)
            return res
        })
    )

    const [hasPermission, setHasPermission] = useState(true)

    // filter
    const [filter, setFilter] = useState(999)
    useEffect(() => {
        filterData({ status: filter })
    }, [filter])


    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('lib.confirmDeleteFile'),
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

    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="absolute right-0 top-[-46px] flex gap-4 items-center">
            <SearchInput placeholder={t('lib.fileName')} onChange={(e) => search(e.target.value)}></SearchInput>
            {hasPermission && <Link to='/filelib/upload'><Button className="px-8" onClick={() => { }}>添加文件</Button></Link>}
        </div>
        <div className="h-[calc(100vh-200px)] overflow-y-auto pb-20">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[600px]">{t('lib.fileName')}</TableHead>
                        {/* 状态 */}
                        <TableHead className="flex items-center gap-4">{t('lib.status')}
                            {/* Select component */}
                            <Select onValueChange={selectChange}>
                                <SelectTrigger className="border-none w-16">
                                    <Filter size={16} className={`cursor-pointer ${filter === 999 ? '' : 'text-gray-950'}`} />
                                </SelectTrigger>
                                <SelectContent className="w-fit">
                                    <SelectGroup>
                                        <SelectItem value={'999'}>{t('all')}</SelectItem>
                                        <SelectItem value={'1'}>{t('lib.parsing')}</SelectItem>
                                        <SelectItem value={'2'}>{t('lib.completed')}</SelectItem>
                                        <SelectItem value={'3'}>{t('lib.parseFailed')}</SelectItem>
                                    </SelectGroup>
                                </SelectContent>
                            </Select>
                        </TableHead>
                        <TableHead>{t('lib.uploadTime')}</TableHead>
                        <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {datalist.map(el => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium">{el.file_name}</TableCell>
                            <TableCell>
                                {el.status === 3 ? <div className="flex items-center">
                                    <div className="tooltip" data-tip={el.remark}>
                                        <span className='text-red-500'>{t('lib.parseFailed')}</span>
                                    </div>
                                    <Button variant="link"><RotateCw size={16} onClick={() => handleRetry([el])} /></Button>
                                </div> :
                                    <span className={el.status === 3 && 'text-red-500'}>{[t('lib.parseFailed'), t('lib.parsing'), t('lib.completed'), t('lib.parseFailed')][el.status]}</span>
                                }
                            </TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell className="text-right">
                                <Button variant="link" disabled={el.status !== 2} className="px-2">查看</Button>
                                {hasPermission ? <Button variant="link" onClick={() => handleDelete(el.id)} className="text-red-500 px-2">{t('delete')}</Button> :
                                    <Button variant="link" className="ml-4 text-gray-400">{t('delete')}</Button>}
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
        {/* <UploadModal id={id} accept={appConfig.libAccepts} open={open} setOpen={handleOpen} onResult={handleUploadResult}></UploadModal> */}
    </div>
};
