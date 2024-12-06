
import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button, LoadButton } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, SearchInput, Textarea } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import Cascader from "@/components/bs-ui/select/cascader";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { createFileLib, deleteFileLib, readFileLibDatabase } from "@/controllers/API";
import { getKnowledgeModelConfig, getModelListApi } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { t } from "i18next";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

function CreateModal({ datalist, open, setOpen, onLoadEnd }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [modal, setModal] = useState(null)
    const [options, setOptions] = useState([])

    // Fetch model data
    useEffect(() => {
        Promise.all([getKnowledgeModelConfig(), getModelListApi()]).then(([config, data]) => {
            const { embedding_model_id } = config
            let embeddings = []
            let models = {}
            let _model = []
            data.forEach(server => {
                const serverItem = { value: server.id, label: server.name, children: [] }
                serverItem.children = server.models.reduce((res, model) => {
                    if (model.model_type !== 'embedding' || !model.online) return res
                    const modelItem = { value: model.id, label: model.model_name }
                    models[model.id] = model.model_name
                    // 找到默认值
                    if (model.id === embedding_model_id) {
                        _model = [serverItem, modelItem]
                    }
                    return [...res, modelItem]
                }, [])
                if (serverItem.children.length) embeddings.push(serverItem)
            });
            setOptions(embeddings)
            setModal(_model)

            onLoadEnd(models)
        })
    }, [])

    const { toast } = useToast()

    const [error, setError] = useState({ name: false, desc: false })

    const [saveLoad, setSaveLoad] = useState(false)
    const handleCreate = async () => {
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

        setSaveLoad(true);
        await captureAndAlertRequestErrorHoc(createFileLib({
            name,
            description: desc,
            model: modal[1].value,
            type: 1
        }).then(res => {
            // @ts-ignore
            window.libname = name
            navigate("/filelib/qalib/" + res.id);
            setOpen(false)
            setSaveLoad(false);
        }))
        setSaveLoad(false);
    }

    const handleError = (list) => {
        toast({
            variant: "error",
            description: list
        })
    }

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('lib.createLibrary')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('lib.libraryName')}</label>
                    <Input name="name" ref={nameRef} placeholder={t('lib.libraryName')} className={`col-span-3 ${error.name && 'border-red-400'}`} />
                </div>
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('lib.description')}</label>
                    <Textarea id="desc" ref={descRef} placeholder={t('lib.description')} className={`col-span-3 ${error.desc && 'border-red-400'}`} />
                </div>
                <div className="">
                    <label htmlFor="roleAndTasks" className="bisheng-label">{t('lib.model')}</label>
                    {
                        modal && <Cascader
                            defaultValue={modal}
                            options={options}
                            onChange={(a, val) => setModal(val)}
                        />
                    }
                </div>
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button" onClick={() => setOpen(false)}>取消</Button>
                </DialogClose>
                <LoadButton loading={saveLoad} type="submit" className="px-11" onClick={handleCreate}>{t('create')}</LoadButton>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

export default function KnowledgeQa(params) {
    const [open, setOpen] = useState(false);
    const [openData, setOpenData] = useState(false);
    const { user } = useContext(userContext);
    const [modelNameMap, setModelNameMap] = useState({})

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({}, (param) => {
        return readFileLibDatabase({ ...param, name: param.keyword, type: 1 })
    })

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('lib.confirmDeleteLibrary'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFileLib(id).then(res => {
                    reload();
                }));
                next()
            },
        })
    }

    // 进详情页前缓存 page, 临时方案
    const handleCachePage = () => {
        window.LibPage = { page, type: 'qa' }
    }
    useEffect(() => {
        const _page = window.LibPage
        if (_page) {
            setPage(_page.page);
            delete window.LibPage
        } else {
            setPage(1);
        }
    }, [])

    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="h-[calc(100vh-128px)] overflow-y-auto pb-20">
            <div className="flex justify-end gap-4 items-center absolute right-0 top-[-44px]">
                <SearchInput placeholder={t('lib.libraryName')} onChange={(e) => search(e.target.value)} />
                <Button className="px-8 text-[#FFFFFF]" onClick={() => setOpen(true)}>{t('create')}</Button>
            </div>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>ID</TableHead>
                        <TableHead className="w-[200px]">{t('lib.libraryName')}</TableHead>
                        <TableHead>{t('lib.model')}</TableHead>
                        <TableHead>{t('createTime')}</TableHead>
                        <TableHead>{t('updateTime')}</TableHead>
                        <TableHead>{t('lib.createUser')}</TableHead>
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>

                <TableBody>
                    {datalist.map((el: any) => (
                        <TableRow key={el.id}>
                            <TableCell>{el.id}</TableCell>
                            <TableCell className="font-medium max-w-[200px]">
                                <div className=" truncate-multiline">{el.name}</div>
                            </TableCell>
                            <TableCell>{modelNameMap[el.model] || '--'}</TableCell>
                            <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell className="max-w-[300px] break-all">
                                <div className=" truncate-multiline">{el.user_name || '--'}</div>
                            </TableCell>
                            <TableCell className="text-right" onClick={() => {
                                // @ts-ignore
                                window.libname = el.name;
                            }}>
                                {/* <Button variant="link" className="" onClick={() => setOpenData(true)}>添加到数据集</Button> */}
                                <Link to={`/filelib/qalib/${el.id}`} className="no-underline hover:underline text-primary" onClick={handleCachePage}>{t('lib.details')}</Link>
                                {user.role === 'admin' || user.user_id === el.user_id ?
                                    <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-4 text-red-500 px-0">{t('delete')}</Button> :
                                    <Button variant="link" className="ml-4 text-gray-400 px-0">{t('delete')}</Button>
                                }
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
        <div className="bisheng-table-footer px-6 bg-background-login">
            <p className="desc">{t('lib.libraryCollection')}</p>
            <div>
                <AutoPagination
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
        <CreateModal datalist={datalist} open={open} setOpen={setOpen} onLoadEnd={setModelNameMap}></CreateModal>
        {/* <SelectData open={openData} setOpen={setOpenData} /> */}
    </div>
};
