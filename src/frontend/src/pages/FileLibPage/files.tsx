import { Link, useParams } from "react-router-dom";
import { Button } from "../../components/ui/button";
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/ui/table";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/ui/tabs";

import { ArrowLeft, Filter, RotateCw, Search } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bsconfirm } from "../../alerts/confirm";
import PaginationComponent from "../../components/PaginationComponent";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectGroup, SelectIconTrigger, SelectItem } from "../../components/ui/select1";
import { locationContext } from "../../contexts/locationContext";
import { deleteFile, readFileByLibDatabase, retryKnowledgeFileApi } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import UploadModal from "../../modals/UploadModal";
import { useTable } from "../../util/hook";

export default function FilesPage() {
    const { t } = useTranslation()

    const { id } = useParams()
    // 上传 上传成功添加到列表
    const [open, setOpen] = useState(false)
    const [title, setTitle] = useState('')

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData, refreshData } = useTable((param) =>
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
        setTitle(window.libname)
    }, [])

    const handleOpen = (e) => {
        setOpen(e)
        reload()
    }

    // 删除
    const { delShow, idRef, close, delConfim } = useDelete()

    const handleDelete = () => {
        captureAndAlertRequestErrorHoc(deleteFile(idRef.current).then(res => {
            reload()
            close()
        }))
    }

    // 上传结果展示
    const handleUploadResult = (fileCount, failFiles) => {
        failFiles.length && bsconfirm({
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

    // 重试解析
    const handleRetry = (id) => {
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(id).then(res => {
            // 乐观更新
            refreshData(
                (item) => item.id === id,
                { status: 1 }
            )
        }))
    }

    const selectChange = (id) => {
        setFilter(Number(id))
    }

    return <div className="w-full h-screen p-6 relative overflow-y-auto">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <ShadTooltip content="back" side="top">
            <button className="extra-side-bar-buttons w-[36px] absolute top-[26px]" onClick={() => { }} >
                <Link to='/filelib'><ArrowLeft className="side-bar-button-size" /></Link>
            </button>
        </ShadTooltip>
        <Tabs defaultValue="account" className="w-full">
            <TabsList className="ml-12">
                <TabsTrigger value="account" className="roundedrounded-xl">{t('lib.fileList')}</TabsTrigger>
                <TabsTrigger disabled value="password">{t('lib.systemIntegration')}</TabsTrigger>
            </TabsList>
            <TabsContent value="account">
                <div className="flex justify-between items-center">
                    <span className=" text-gray-800">{title}</span>
                    <div className="flex gap-4 items-center">
                        <div className="w-[180px] relative">
                            <Input placeholder={t('lib.fileName')} onChange={(e) => search(e.target.value)}></Input>
                            <Search className="absolute right-4 top-2 text-gray-300 pointer-events-none"></Search>
                        </div>
                        {hasPermission && <Button className="h-8 rounded-full" onClick={() => setOpen(true)}>{t('lib.upload')}</Button>}
                    </div>
                </div>
                <Table>
                    <TableCaption>
                        <div className="join grid grid-cols-2 w-[200px]">
                            <PaginationComponent
                                page={page}
                                pageSize={pageSize}
                                total={total}
                                onChange={(newPage) => setPage(newPage)}
                            />
                        </div>
                    </TableCaption>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[600px]">{t('lib.fileName')}</TableHead>
                            {/* 状态 */}
                            <TableHead className="flex items-center gap-4">{t('lib.status')}
                                {/* Select component */}
                                <Select onValueChange={selectChange}>
                                    <SelectIconTrigger className="">
                                        <Filter size={16} className={`cursor-pointer ${filter === 999 ? '' : 'text-gray-950'}`} />
                                    </SelectIconTrigger>
                                    <SelectContent className="">
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
                            <TableHead>{t('operations')}</TableHead>
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
                                        <Button variant="link"><RotateCw size={16} onClick={() => handleRetry(el.id)} /></Button>
                                    </div> :
                                        <span className={el.status === 3 && 'text-red-500'}>{[t('lib.parseFailed'), t('lib.parsing'), t('lib.completed'), t('lib.parseFailed')][el.status]}</span>
                                    }
                                </TableCell>
                                <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                                <TableCell className="text-right">
                                    {hasPermission ? <a href="javascript:;" onClick={() => delConfim(el.id)} className="underline ml-4">{t('delete')}</a> :
                                        <a href="javascript:;" className="underline ml-4 text-gray-400">{t('delete')}</a>}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
                {/* Pagination */}
            </TabsContent>
            <TabsContent value="password"></TabsContent>
        </Tabs>
        {/* upload modal */}
        <UploadModal id={id} accept={appConfig.libAccepts} open={open} setOpen={handleOpen} onResult={handleUploadResult}></UploadModal>
        {/* Delete confirmation */}
        <dialog className={`modal ${delShow && 'modal-open'}`}>
            <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background">
                <h3 className="font-bold text-lg">{t('prompt')}</h3>
                <p className="py-4">{t('lib.confirmDeleteFile')}</p>
                <div className="modal-action">
                    <Button className="h-8 rounded-full" variant="outline" onClick={close}>{t('cancel')}</Button>
                    <Button className="h-8 rounded-full" variant="destructive" onClick={handleDelete}>{t('delete')}</Button>
                </div>
            </form>
        </dialog>
    </div>
};


const useDelete = () => {
    const [delShow, setDelShow] = useState(false)
    const idRef = useRef<any>(null)

    return {
        delShow,
        idRef,
        close: () => {
            setDelShow(false)
        },
        delConfim: (id) => {
            idRef.current = id
            setDelShow(true)
        }
    }
}