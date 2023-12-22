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

import { ArrowLeft } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { locationContext } from "../../contexts/locationContext";
import { deleteFile, readFileByLibDatabase } from "../../controllers/API";
import UploadModal from "../../modals/UploadModal";

export default function FilesPage() {
    const { t } = useTranslation()

    const { id } = useParams()
    // 上传 上传成功添加到列表
    const [open, setOpen] = useState(false)
    const [loading, setLoading] = useState(false)

    const [title, setTitle] = useState('')
    const [page, setPage] = useState(1)
    const [datalist, setDataList] = useState([])
    const [pageEnd, setPageEnd] = useState(false)
    const pages = useRef(1)

    const [hasPermission, setHasPermission] = useState(true)
    const { appConfig } = useContext(locationContext)

    const loadPage = (_page) => {
        setLoading(true)
        readFileByLibDatabase(id, _page).then(res => {
            const { data, writeable, pages: ps } = res
            pages.current = ps
            setDataList(data)
            setPage(_page)
            setPageEnd(!data.length)
            setLoading(false)
            setHasPermission(writeable)
        })
    }
    useEffect(() => {
        // @ts-ignore
        setTitle(window.libname)
        loadPage(1)
    }, [])

    const handleOpen = (e) => {
        setOpen(e)
        loadPage(page)
    }

    // 删除
    const { delShow, idRef, close, delConfim } = useDelete()

    const handleDelete = () => {
        deleteFile(idRef.current).then(res => {
            loadPage(page)
            close()
        })
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
                    {hasPermission && <Button className="h-8 rounded-full" onClick={() => { setOpen(true) }}>{t('lib.upload')}</Button>}
                </div>
                <Table>
                    <TableCaption>
                        <div className="join grid grid-cols-2 w-[200px]">
                            <button disabled={page === 1} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page - 1)}>{t('previousPage')}</button>
                            <button disabled={page >= pages.current || pageEnd} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page + 1)}>{t('nextPage')}</button>
                        </div>
                    </TableCaption>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[600px]">{t('lib.fileName')}</TableHead>
                            <TableHead>{t('lib.status')}</TableHead>
                            <TableHead>{t('lib.uploadTime')}</TableHead>
                            <TableHead>{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map(el => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">{el.file_name}</TableCell>
                                <TableCell>
                                    {el.status === 3 ? <div className="tooltip" data-tip={el.remark}>
                                        <span className='text-red-500'>{t('lib.parseFailed')}</span>
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
        <UploadModal id={id} accept={appConfig.libAccepts} open={open} setOpen={handleOpen}></UploadModal>
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