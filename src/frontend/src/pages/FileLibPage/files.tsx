import { Link, useParams } from "react-router-dom";
import { Button } from "../../components/bs-ui/button";
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/bs-ui/tabs";

import { ArrowLeft, Filter, RotateCw, Search, X } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
// import PaginationComponent from "../../components/PaginationComponent";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination"
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Input, SearchInput } from "../../components/bs-ui/input";
import { Select, SelectContent, SelectGroup, SelectTrigger, SelectItem } from "../../components/bs-ui/select";
import { locationContext } from "../../contexts/locationContext";
import { deleteFile, readFileByLibDatabase, retryKnowledgeFileApi } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import UploadModal from "../../modals/UploadModal";
import { useTable } from "../../util/hook";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

export default function FilesPage() {
    const { t } = useTranslation()

    const { id } = useParams()
    // 上传 上传成功添加到列表
    const [open, setOpen] = useState(false)
    const [title, setTitle] = useState('')

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData, refreshData } = useTable({}, (param) =>
        readFileByLibDatabase({ ...param, id, name: param.keyword }).then(res => {
            setHasPermission(res.writeable)
            return res
        })
    )

    const [hasPermission, setHasPermission] = useState(true)
    const { appConfig } = useContext(locationContext)

    // filter
    const [filter, setFilter] = useState(999)
    useEffect(() => {
        filterData({ status: filter })
    }, [filter])

    useEffect(() => {
        // @ts-ignore
        const libname = window.libname // 临时记忆
        if (libname) {
            localStorage.setItem('libname', window.libname)
        }
        setTitle(window.libname || localStorage.getItem('libname'))
    }, [])

    const handleOpen = (e) => {
        setOpen(e)
        reload()
    }

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

    const [repeatFiles, setRepeatFiles] = useState([])
    // 上传结果展示
    const handleUploadResult = (fileCount, failFiles, res) => {
        const _repeatFiles = res.filter(e => e.status === 3)
        if (_repeatFiles.length) {
            setRepeatFiles(_repeatFiles)
        } else {
            failFiles.length && bsConfirm({
                desc: <div>
                    <p>{t('lib.fileUploadResult', { total: fileCount, failed: failFiles.length })}</p>
                    <div className="max-h-[160px] overflow-y-auto no-scrollbar">
                        {failFiles.map(str => <p className=" text-red-400" key={str}>{str}</p>)}
                    </div>
                </div>,
                onOk(next) {
                    next()
                }
            })
        }
    }

    // 重试解析
    const [retryLoad, setRetryLoad] = useState(false)
    const handleRetry = (objs) => {
        setRetryLoad(true)
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(objs).then(res => {
            // 乐观更新
            // refreshData(
            //     (item) => ids.includes(item.id),
            //     { status: 1 }
            // )
            reload()
            setRepeatFiles([])
            setRetryLoad(false)
        }))
    }

    const selectChange = (id) => {
        setFilter(Number(id))
    }

    return <div className="w-full h-full px-2 py-4 relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <ShadTooltip content="back" side="top">
            <button className="extra-side-bar-buttons w-[36px] absolute top-[16px]" onClick={() => { }} >
                <Link to='/filelib'><ArrowLeft className="side-bar-button-size" /></Link>
            </button>
        </ShadTooltip>
        <div className="h-full overflow-y-auto pb-10 bg-[#fff]">
            <div className="flex justify-between items-center">
                <span className=" text-gray-700 text-sm font-black pl-14">{title}</span>
                <div className="flex gap-4 items-center">
                    <SearchInput placeholder={t('lib.fileName')} onChange={(e) => search(e.target.value)}></SearchInput>
                    {hasPermission && <Button className="px-8" onClick={() => setOpen(true)}>{t('lib.upload')}</Button>}
                </div>
            </div>
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
                                {hasPermission ? <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-4 text-red-500">{t('delete')}</Button> :
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
        {/* upload modal */}
        <UploadModal id={id} accept={appConfig.libAccepts} open={open} setOpen={handleOpen} onResult={handleUploadResult}></UploadModal>
        {/* 重复文件提醒 */}
        <dialog className={`modal ${repeatFiles.length && 'modal-open'}`}>
    <div className="modal-box w-[560px] bg-[#fff] shadow-lg dark:bg-background">
        <h3 className="font-bold text-lg relative">{t('lib.modalTitle')}
            <X className="absolute right-0 top-0 text-gray-400 cursor-pointer" size={20} onClick={() => setRepeatFiles([])}></X>
        </h3>
        <p className="py-4">{t('lib.modalMessage')}</p>
        <ul className="overflow-y-auto max-h-[400px]">
            {repeatFiles.map(el => (
                <li key={el.id} className="py-2 text-red-500">{el.remark}</li>
            ))}
        </ul>
        <div className="modal-action">
            <Button className="h-8" variant="outline" onClick={() => setRepeatFiles([])}>{t('lib.keepOriginal')}</Button>
            <Button className="h-8" disabled={retryLoad} onClick={() => handleRetry(repeatFiles)}>
                {retryLoad && <span className="loading loading-spinner loading-xs"></span>}{t('lib.override')}
            </Button>
        </div>
    </div>
</dialog>

    </div >
};
