import { Link, useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import {
    Table,
    TableBody,
    TableCaption,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "../../components/ui/table";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/ui/tabs";

import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Dropdown from "../../components/dropdownComponent";
import { Textarea } from "../../components/ui/textarea";
import { alertContext } from "../../contexts/alertContext";
import { userContext } from "../../contexts/userContext";
import { createFileLib, deleteFileLib, getEmbeddingModel, readFileLibDatabase } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import PaginationComponent from "../../components/PaginationComponent";
import { useTable } from "../../util/hook";
import { Search } from "lucide-react";

function CreateModal({ datalist, open, setOpen }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [modal, setModal] = useState('')
    const [options, setOptions] = useState([])

    // Fetch model data
    useEffect(() => {
        getEmbeddingModel().then(res => {
            const models = res.models || []
            setOptions(models)
            setModal(models[0] || '')
        })
    }, [])

    const { setErrorData } = useContext(alertContext);

    const [error, setError] = useState({ name: false, desc: false })

    const handleCreate = () => {
        const name = nameRef.current.value
        const desc = descRef.current.value
        const errorlist = []

        if (!name) errorlist.push(t('lib.enterLibraryName'))
        if (name.length > 30) errorlist.push(t('lib.libraryNameLimit'))
        if (!modal) errorlist.push(t('lib.selectModel'))

        if (datalist.find(data => data.name === name)) errorlist.push(t('lib.nameExists'))
        const nameErrors = errorlist.length

        if (desc.length > 200) errorlist.push(t('lib.descriptionLimit'))
        setError({ name: !!nameErrors, desc: errorlist.length > nameErrors })
        if (errorlist.length) return handleError(errorlist)

        captureAndAlertRequestErrorHoc(createFileLib({
            name,
            description: desc,
            model: modal
        }).then(res => {
            // @ts-ignore
            window.libname = name
            navigate("/filelib/" + res.id);
            setOpen(false)
        }))
    }

    const handleError = (list) => {
        setErrorData({
            title: t('prompt'),
            list
        });
    }

    return <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
        <form method="dialog" className="max-w-[600px] flex flex-col modal-box bg-[#fff] shadow-lg dark:bg-background" onClick={e => e.stopPropagation()}>
            <button className="btn btn-sm btn-circle btn-ghost absolute right-2 top-2" onClick={() => setOpen(false)}>✕</button>
            <h3 className="font-bold text-lg">{t('lib.createLibrary')}</h3>
            <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                <div className="grid gap-4 py-4 mt-2">
                    <div className="grid grid-cols-4 items-center gap-4">
                        <Label htmlFor="name" className="text-right">{t('lib.libraryName')}</Label>
                        <Input id="name" ref={nameRef} placeholder={t('lib.libraryName')} className={`col-span-3 ${error.name && 'border-red-400'}`} />
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                        <Label htmlFor="desc" className="text-right">{t('lib.description')}</Label>
                        <Textarea id="desc" ref={descRef} placeholder={t('lib.description')} className={`col-span-3 ${error.desc && 'border-red-400'}`} />
                    </div>
                    <div className="grid grid-cols-4 items-center gap-4">
                        <Label className="text-right">{t('lib.model')}</Label>
                        <Dropdown
                            options={options}
                            onSelect={(val) => setModal(val)}
                            value={modal}
                        ></Dropdown>
                    </div>
                    <Button type="submit" className="mt-6 h-8 rounded-full" onClick={handleCreate}>{t('create')}</Button>
                </div>
            </div>
        </form>
    </dialog>
}

export default function FileLibPage() {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable((param) =>
        readFileLibDatabase(param.page, param.pageSize, param.keyword)
    )

    // Delete
    const { delShow, idRef, close, delConfirm } = useDelete();

    const handleDelete = () => {
        captureAndAlertRequestErrorHoc(deleteFileLib(idRef.current.id).then(res => {
            reload();
            close();
        }));
    }

    // 进详情页前缓存 page, 临时方案
    const handleCachePage = () => {
        window.LibPage = page
    }
    useEffect(() => {
        const _page = window.LibPage
        if (_page) {
            setPage(_page);
            delete window.LibPage
        } else {
            setPage(1);
        }
    }, [])


    const { t } = useTranslation();

    return (
        <div className="w-full h-screen p-6 overflow-y-auto">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <span className="loading loading-infinity loading-lg"></span>
            </div>}

            <Tabs defaultValue="account" className="w-full">
                <TabsList className="">
                    <TabsTrigger value="account" className="roundedrounded-xl">{t('lib.fileData')}</TabsTrigger>
                    <TabsTrigger disabled value="password">{t('lib.structuredData')}</TabsTrigger>
                </TabsList>

                <TabsContent value="account">
                    <div className="flex justify-end gap-4 items-center">
                        <div className="w-[180px] relative">
                            <Input placeholder={t('lib.libraryName')} onChange={(e) => search(e.target.value)}></Input>
                            <Search className="absolute right-4 top-2 text-gray-300 pointer-events-none"></Search>
                        </div>
                        <Button className="h-8 rounded-full" onClick={() => setOpen(true)}>{t('create')}</Button>
                    </div>
                    <Table>
                        <TableCaption>
                            <p>{t('lib.libraryCollection')}</p>
                            <div className="">
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
                                <TableHead className="w-[200px]">{t('lib.libraryName')}</TableHead>
                                <TableHead>{t('lib.model')}</TableHead>
                                <TableHead>{t('createTime')}</TableHead>
                                <TableHead>{t('updateTime')}</TableHead>
                                <TableHead>{t('lib.createUser')}</TableHead>
                                <TableHead className="text-right"></TableHead>
                            </TableRow>
                        </TableHeader>

                        <TableBody>
                            {datalist.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.model || '--'}</TableCell>
                                    <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                                    <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                    <TableCell>{el.user_name || '--'}</TableCell>
                                    <TableCell className="text-right" onClick={() => {
                                        // @ts-ignore
                                        window.libname = el.name;
                                    }}>
                                        <Link to={`/filelib/${el.id}`} className="underline" onClick={handleCachePage}>{t('lib.details')}</Link>
                                        {user.role === 'admin' || user.user_id === el.user_id ?
                                            <a href="javascript:;" onClick={() => delConfirm(el)} className="underline ml-4">{t('delete')}</a> :
                                            <a href="javascript:;" className="underline ml-4 text-gray-400">{t('delete')}</a>
                                        }
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TabsContent>
                <TabsContent value="password"></TabsContent>
            </Tabs>

            <CreateModal datalist={datalist} open={open} setOpen={setOpen}></CreateModal>

            <dialog className={`modal ${delShow && 'modal-open'}`}>
                <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background">
                    <h3 className="font-bold text-lg">{t('prompt')}</h3>
                    <p className="py-4">{t('lib.confirmDeleteLibrary')}</p>
                    <div className="modal-action">
                        <Button className="h-8 rounded-full" variant="outline" onClick={close}>{t('cancel')}</Button>
                        <Button className="h-8 rounded-full" variant="destructive" onClick={handleDelete}>{t('delete')}</Button>
                    </div>
                </form>
            </dialog>
        </div>
    );
}



const useDelete = () => {
    const [delShow, setDelShow] = useState(false)
    const idRef = useRef<any>(null)

    return {
        delShow,
        idRef,
        close: () => {
            setDelShow(false)
        },
        delConfirm: (id) => {
            idRef.current = id
            setDelShow(true)
        }
    }
}
