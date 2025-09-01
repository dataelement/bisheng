import { Link, useNavigate } from "react-router-dom";
import { Button } from "../../components/bs-ui/button";
import { Input, SearchInput } from "../../components/bs-ui/input";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";

import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Textarea } from "../../components/bs-ui/input";
import { userContext } from "../../contexts/userContext";
import { copyLibDatabase, createFileLib, deleteFileLib, readFileLibDatabase } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
// import PaginationComponent from "../../components/PaginationComponent";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import Cascader from "@/components/bs-ui/select/cascader";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getKnowledgeModelConfig, getModelListApi } from "@/controllers/API/finetune";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { useTable } from "../../util/hook";
import { CircleAlert, Copy, Ellipsis, LoaderCircle, Settings, Trash2 } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@radix-ui/react-dropdown-menu";

function CreateModal({ datalist, open, setOpen, onLoadEnd, mode = 'create', currentLib = null }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [modal, setModal] = useState(null)
    const [options, setOptions] = useState([])
    const [isSubmitting, setIsSubmitting] = useState(false) // 新增loading状态
    const [isModelChanged, setIsModelChanged] = useState(false) // 新增：跟踪模型是否被修改

    useEffect(() => {
        if (mode === 'edit' && currentLib) {
            if (nameRef.current) nameRef.current.value = currentLib.name;
            if (descRef.current) descRef.current.value = currentLib.description;
            setIsModelChanged(false) // 初始化时不显示警告
            // const currentModel = 
            //   setModal(currentModel);
        }
    }, [mode, currentLib]);
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
                    models[model.id] = server.name + '/' + model.model_name
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
        }).catch(error => {  // 添加错误处理
            toast({
                variant: "error",
                description: '加载模型出错'
            })
        })
    }, [])

    const { toast } = useToast()
    const [error, setError] = useState({ name: false, desc: false })

    const handleCreate = async (e, isImport = false) => {
        const name = nameRef.current.value
        let desc = descRef.current.value
        if (!desc) {
            desc = `当回答与${name}相关的问题时，参考此知识库`;
        }
        const errorlist = []

        if (!name) errorlist.push(t('lib.enterLibraryName'))
        if (name.length > 200) errorlist.push('知识库名称不能超过200字')
        if (!modal) errorlist.push(t('lib.selectModel'))
        if (datalist.find(data => data.name === name)) errorlist.push(t('lib.nameExists'))

        if (desc.length > 200) errorlist.push(t('lib.descriptionLimit'))



        setIsSubmitting(true)  // 开始提交
        //     try {
        //   if (mode === 'create') {
        //     // 创建逻辑...
        //   } else {}
        // }
        await captureAndAlertRequestErrorHoc(createFileLib({
            name,
            description: desc || `当回答与${name}相关的问题时，参考此知识库`,
            model: modal[1].value,
            type: 0
        }).then(res => {
            // @ts-ignore
            window.libname = [name, desc]
            navigate(isImport
                ? `/filelib/upload/${res.id}`  // 导入模式
                : `/filelib/${res.id}`         // 普通模式
            );
            setOpen(false)
            setIsSubmitting(false)
        }))
        setIsSubmitting(false)
    }

    const handleError = (list) => {
        toast({
            variant: 'error',
            description: list
        });
    }

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{mode === 'create' ? t('lib.createLibrary') : '知识库设置'}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                {mode === 'edit' && (
                    <div className="space-y-4"> {/* 上下排列 */}
                        <div className="flex items-center gap-48"> {/* 左右排列 */}
                            <label className="bisheng-label text-sm text-gray-500">{t('lib.knowledgeBaseId')}</label>
                            <div className="text-sm">{currentLib?.id || ''}</div>
                        </div>
                        <div className="flex items-center gap-48"> {/* 左右排列 */}
                            <label className="bisheng-label text-sm text-gray-500">{t('createTime')}</label>
                            <div className="text-sm">
                                {currentLib?.create_time ? currentLib.create_time.replace('T', ' ') : ''}
                            </div>
                        </div>
                    </div>
                )}
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('lib.libraryName')}</label>
                    <span className="text-red-500">*</span>
                    <Input name="name" ref={nameRef} placeholder={t('lib.enterLibraryName')} className={`col-span-3 ${error.name && 'border-red-400'}`} />
                </div>
                <div className="">
                    <label htmlFor="name" className="bisheng-label">知识库描述</label>
                    <Textarea
                        id="desc"
                        ref={descRef}
                        placeholder="请输入知识库描述"
                        rows={8}
                        className={`col-span-3 ${error.desc && 'border-red-400'}`}
                    />
                </div>
                <div className="">
                    <label htmlFor="roleAndTasks" className="bisheng-label">知识库embedding模型选择</label>
                    {
                        modal && <Cascader
                            defaultValue={modal}
                            placholder="请在模型管理中配置 embedding 模型"
                            options={options}
                            onChange={(a, val) => {
                                setModal(val);
                                if (mode === 'edit') setIsModelChanged(true); // 仅在编辑模式下标记变更
                            }}
                        />
                    }
                    {mode === 'edit' && isModelChanged && (
                        <p className="text-red-500 text-sm mt-1 flex items-center gap-1">
                            <CircleAlert className="w-4 h-4" color="#ef4444" />
                            修改 embedding 模型可能会消耗大量模型资源且耗时较久，请谨慎进行
                        </p>
                    )}
                </div>
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-8 h-8">{t('cancel')}</Button>
                </DialogClose>
                <Button
                    variant="outline"
                    className="px-8 h-8 flex"
                    onClick={(e) => handleCreate(e, false)}
                    disabled={isSubmitting}
                >
                    {isSubmitting && <LoadIcon className="mr-1" />}
                    完成创建
                </Button>
                <Button
                    type="submit"
                    className="px-8 h-8 flex"
                    onClick={(e) => handleCreate(e, true)}
                    disabled={isSubmitting}
                >
                    {isSubmitting && <LoadIcon className="mr-1" />}
                    {t('createImport')}
                </Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

const doing = {} // 记录copy中的知识库
export default function KnowledgeFile() {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);
    const [modelNameMap, setModelNameMap] = useState({})
    const { message } = useToast()
    const navigate = useNavigate()
    const [menuOpen, setMenuOpen] = useState(false);
    const [openMenus, setOpenMenus] = useState<Record<string, boolean>>({});
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [currentSettingLib, setCurrentSettingLib] = useState(null);
    const [copyLoadingId, setCopyLoadingId] = useState<string | null>(null);

    const toggleMenu = (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        setOpenMenus(prev => ({
            ...Object.keys(prev).reduce((acc, key) => {
                acc[key] = false; // 关闭其他所有菜单
                return acc;
            }, {} as Record<string, boolean>),
            [id]: !prev[id] // 切换当前菜单
        }));
        // @ts-ignore
        window.libname = [el.name, el.description];
    };

    // 点击外部关闭菜单
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (!(event.target as Element).closest('.menu-container')) {
                setOpenMenus({});
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({ cancelLoadingWhenReload: true }, (param) =>
        readFileLibDatabase({ ...param, name: param.keyword })
    )

    // 复制中开启轮询
    useEffect(() => {
        const todos = datalist.reduce((prev, curr) => {
            if (curr.state === 1) {
                prev.push({ id: curr.id, name: curr.name })
            } else {
                doing[curr.id] = true
            }
            return prev
        }, [])

        todos.map(todo => {
            if (doing[todo.id]) {
                message({
                    variant: 'success',
                    description: `${todo.name} 复制完成`
                })
                delete doing[todo.id]
            }
        })

        todos.length && setTimeout(() => {
            reload()
        }, 5000);
    }, [datalist])

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
        window.LibPage = { page, type: 'file' }
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


    const { t, i18n } = useTranslation();
    useEffect(() => {
        i18n.loadNamespaces('knowledge');
    }, [i18n]);

    // copy
    const handleCopy = async (elem) => {
        const newName = `${elem.name}的副本`;
        if (newName.length > 200) {
            message({
                variant: 'error',
                description: '复制失败：复制后的知识库名称超过200字限制'
            });
            return;
        }
        setCopyLoadingId(elem.id); // 设置当前正在复制的ID
        doing[elem.id] = true; // 标记为正在复制
        try {
            await captureAndAlertRequestErrorHoc(copyLibDatabase(elem.id));
            reload();
        } catch (error) {
            message({
                variant: 'error',
                description: '复制失败'
            });
        } finally {
            setCopyLoadingId(null); // 重置加载状态
        }
    }

    return (
        <div className="relative">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}
            <div className="h-[calc(100vh-128px)] overflow-y-auto pb-20">
                <div className="flex justify-end gap-4 items-center absolute right-0 top-[-44px]">
                    <SearchInput placeholder={t('lib.searchPlaceholder')} onChange={(e) => search(e.target.value)} />
                    <Button className="px-8 text-[#FFFFFF]" onClick={() => setOpen(true)}>{t('create')}</Button>
                </div>
                <Table>
                    <TableHeader>
                        <TableRow>
                            {/* <TableHead>{t('lib.knowledgeBaseId')}</TableHead> */}
                            <TableHead>{t('lib.libraryName')}</TableHead>
                            {/* <TableHead>{t('lib.model')}</TableHead> */}
                            {/* <TableHead>{t('createTime')}</TableHead> */}
                            <TableHead>{t('updateTime')}</TableHead>
                            <TableHead>{t('lib.createUser')}</TableHead>
                            <TableHead className="text-right">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el: any) => (
                            <TableRow
                                key={el.id}
                                onClick={() => {
                                    window.libname = [el.name, el.description];
                                    navigate(`/filelib/${el.id}`)
                                    handleCachePage()
                                }}
                            >
                                {/* <TableCell>{el.id}</TableCell> */}
                                <TableCell className="font-medium max-w-[200px]">
                                    <div className="flex items-start gap-2">
                                        <img
                                            src={__APP_ENV__.BASE_URL + "/assets/file-logo.svg"}
                                            alt=""
                                            className="w-8 h-8 mt-1 rounded object-cover"
                                        />

                                        <div>
                                            <div className="line-clamp-2">{el.name}</div>
                                            <div
                                                className="line-clamp-2 relative group"
                                                title={el.description.length > 20 ? el.description : undefined}
                                            >
                                                {el.description.length > 20 ? `${el.description.substring(0, 20)}...` : el.description}
                                                {el.description.length > 20 && (
                                                    <div className="absolute hidden group-hover:block bottom-full left-0 bg-blue-500 text-white p-2 rounded whitespace-normal w-48 z-10">
                                                        {el.description}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </TableCell>
                                {/* <TableCell>{modelNameMap[el.model] || '--'}</TableCell> */}
                                {/* <TableCell>{el.create_time.replace('T', ' ')}</TableCell> */}
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                <TableCell className="max-w-[300px] break-all">
                                    <div className=" truncate-multiline">{el.user_name || '--'}</div>
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-2">
                                        <DropdownMenu>
                                            <DropdownMenuTrigger asChild>
                                                <button
                                                    className="w-10 h-10 bg-gray-200 rounded flex items-center justify-center
                    hover:bg-gray-300 transition-colors duration-200
                    focus:outline-none focus:ring-2 focus:ring-gray-400 relative"
                                                    disabled={copyLoadingId === el.id}
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    {copyLoadingId === el.id ? (
                                                        <>
                                                            <LoaderCircle className="animate-spin" />
                                                            <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 bg-white text-gray-800 text-xs px-2 py-1 rounded whitespace-nowrap border border-gray-300 shadow-sm">
                                                                复制中
                                                            </div>
                                                        </>
                                                    ) : (
                                                        <Ellipsis size={24} color="#a69ba2" strokeWidth={1.75} />
                                                    )}
                                                </button>
                                            </DropdownMenuTrigger>

                                            <DropdownMenuContent
                                                align="end"
                                                className=" rounded-md shadow-lg py-1 border border-gray-200 z-[100]"
                                                style={{
                                                    backgroundColor: 'white',
                                                    opacity: 1,
                                                }}
                                                onInteractOutside={() => setOpenMenus({})}
                                            >
                                                {/* 复制按钮 */}
                                                {(el.copiable || user.role === 'admin') && (
                                                    <DropdownMenuItem
                                                        className={`flex items-center gap-2 px-4 py-2 ${el.state === 1 ? 'hover:bg-gray-100 cursor-pointer' : 'text-gray-400 cursor-not-allowed'
                                                            }`}
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            if (el.state === 1) {
                                                                handleCopy(el);
                                                            }
                                                        }}
                                                        disabled={el.state !== 1}
                                                    >
                                                        <Copy className="w-4 h-4" />
                                                        {el.state === 1 ? t('lib.copy') : t('lib.copying')}
                                                    </DropdownMenuItem>
                                                )}

                                                {/* 设置按钮 */}
                                                <DropdownMenuItem
                                                    className="flex items-center gap-2 px-4 py-2 hover:bg-gray-100 cursor-pointer"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setCurrentSettingLib(el);
                                                        setSettingsOpen(true);
                                                    }}
                                                >
                                                    <Settings className="w-4 h-4" />
                                                    {t('设置')}
                                                </DropdownMenuItem>

                                                {/* 删除按钮 */}
                                                <DropdownMenuItem
                                                    className={`flex items-center gap-2 px-4 py-2 ${el.copiable ? ' hover:bg-gray-100' : 'text-gray-400 cursor-not-allowed'
                                                        }`}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        if (el.copiable) {
                                                            handleDelete(el.id);
                                                        }
                                                    }}
                                                    disabled={!el.copiable}
                                                >
                                                    <Trash2 className="w-4 h-4" />
                                                    {t('delete')}
                                                </DropdownMenuItem>
                                            </DropdownMenuContent>
                                        </DropdownMenu>
                                    </div>
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
            <CreateModal datalist={datalist} open={open} setOpen={setOpen} onLoadEnd={setModelNameMap} mode="create"></CreateModal>
            <CreateModal
                datalist={datalist}
                open={settingsOpen}
                setOpen={setSettingsOpen}
                onLoadEnd={reload}
                mode="edit"
                currentLib={currentSettingLib}
            />
        </div>
    );
}