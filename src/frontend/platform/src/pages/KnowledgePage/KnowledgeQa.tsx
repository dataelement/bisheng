import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
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
import { Ellipsis, Trash2 } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import index from "../BuildPage/bench/LingSiWork";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@radix-ui/react-dropdown-menu";
import { QuestionTooltip, TooltipContent, TooltipTrigger } from "@/components/bs-ui/tooltip";

function CreateModal({ datalist, open, setOpen, onLoadEnd }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [modal, setModal] = useState(null)
    const [options, setOptions] = useState([])
    const [isSubmitting, setIsSubmitting] = useState(false) // 新增loading状态

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

    const handleCreate = async () => {
        const name = nameRef.current.value;
        // 1. 获取用户输入的描述，若为空则生成默认描述
        let desc = descRef.current.value || ''; // 先保留原始输入（空或用户输入）

        // 关键：未输入描述时，自动生成默认文本（拼接知识库名称）
        if (!desc.trim()) { // 用 trim() 排除“只输入空格”的情况
            desc = `当回答与${name}相关的问题时，参考此知识库`;
        }

        const errorlist = [];

        // 2. 原有校验逻辑不变（仅名称校验，描述此时已确保有值）
        if (!name) errorlist.push(t('lib.enterLibraryName'));
        if (name.length > 30) errorlist.push(t('lib.libraryNameLimit'));
        if (!modal) errorlist.push(t('lib.selectModel'));
        if (datalist.find(data => data.name === name)) errorlist.push(t('lib.nameExists'));

        // 3. 描述长度校验（默认描述可能因名称过长超200字，需保留校验）
        if (desc.length > 200) errorlist.push(t('lib.descriptionLimit'));

        const nameErrors = errorlist.length;
        setError({ name: !!nameErrors, desc: errorlist.length > nameErrors });
        if (errorlist.length) return handleError(errorlist);

        // 4. 提交逻辑不变（此时 desc 要么是用户输入，要么是默认生成的文本）
        setIsSubmitting(true);
        await captureAndAlertRequestErrorHoc(createFileLib({
            name,
            description: desc, // 提交自动生成的默认描述
            model: modal[1].value,
            type: 1
        }).then(res => {
            window.libname = name;
            navigate("/filelib/qalib/" + res.id);
            setOpen(false);
            setIsSubmitting(false);
        }));
        setIsSubmitting(false);
    };

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
                    <span className="text-red-500">*</span>
                    <Input name="name" ref={nameRef} placeholder={t('请输入知识库名称')} className={`col-span-3 ${error.name && 'border-red-400'}`} />
                </div>
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('lib.description')}</label>
                    <Textarea id="desc" ref={descRef} placeholder={t('请输入知识库描述')} className={`col-span-3 ${error.desc && 'border-red-400'}`} />
                </div>
                <div className="">
                    <label htmlFor="roleAndTasks" className="bisheng-label">{t('lib.model')}</label>
                    {
                        modal && <Cascader
                            defaultValue={modal}
                            placholder="请在模型管理中配置 embedding 模型"
                            options={options}
                            onChange={(a, val) => setModal(val)}
                        />
                    }
                </div>
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11">{t('cancel')}</Button>
                </DialogClose>
                <Button
                    type="submit"
                    className="px-11 flex"
                    onClick={handleCreate}
                    disabled={isSubmitting}
                >
                    {isSubmitting && <LoadIcon className="mr-1" />}
                    {t('create')}
                </Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

export default function KnowledgeQa(params) {
    const [open, setOpen] = useState(false);
    const [openData, setOpenData] = useState(false);
    const { user } = useContext(userContext);
    const [modelNameMap, setModelNameMap] = useState({})
    const navigate = useNavigate()
    const [copyLoadingId, setCopyLoadingId] = useState<string | null>(null);
    const [openMenus, setOpenMenus] = useState<Record<string, boolean>>({});

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

    const toggleMenu = (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        setOpenMenus(prev => ({
            ...Object.keys(prev).reduce((acc, key) => {
                acc[key] = false; // 关闭其他所有菜单
                return acc;
            }, {} as Record<string, boolean>),
            [id]: !prev[id] // 切换当前菜单
        }));
        // 移除无效代码：el未定义，之前导致控制台报错影响功能
        // @ts-ignore
        // window.libname = [el.name, el.description];
    };

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
            {/* 搜索+创建按钮区域：调整top避免遮挡 */}
            <div className="flex justify-end gap-4 items-center absolute right-0 top-[-44px] z-1">
                <SearchInput placeholder={t('lib.libraryName')} onChange={(e) => search(e.target.value)} />
                <Button className="px-8 text-[#FFFFFF]" onClick={() => setOpen(true)}>{t('create')}</Button>
            </div>

            <Table>
                <TableHeader>
                    <TableRow className="w-full">
                        <TableHead className="flex: 1 text-left pr-6">
                            {t('lib.libraryName')}
                        </TableHead>
                        <TableHead className="flex: 1 text-left pl-2">
                            {t('updateTime')}
                        </TableHead>
                        <TableHead className="flex: 1 text-left pl-2">
                            {t('lib.createUser')}
                        </TableHead>
                        <TableHead className="flex: 1 text-right pl-2">
                            {t('operations')}
                        </TableHead>
                    </TableRow>
                </TableHeader>

                <TableBody>
                    {datalist.map((el: any) => (
                        <TableRow
                            key={el.id}
                            // 行hover样式：仅非按钮区域生效
                            className="hover:bg-gray-50 transition-colors"
                            onClick={() => {
                                window.libname = [el.name, el.description];
                                navigate(`/filelib/qalib/${el.id}`);
                                handleCachePage();
                            }}
                        >
                            {/* 名称+描述单元格：恢复原有气泡结构，确保蓝色生效 */}
                            <TableCell className="flex: 1 font-medium max-w-[200px] overflow-visible">
                                <div className="flex items-start gap-2">
                                    <img
                                        src={__APP_ENV__.BASE_URL + "/assets/qa-logo.svg"}
                                        alt="知识库图标"
                                        className="w-[50px] h-[50px] mt-1 flex-shrink-0"
                                    />

                                    <div className="min-w-0 overflow-visible">
                                        {/* 知识库名称（不变） */}
                                        <div className="truncate max-w-[500px] text-[18px] font-medium mb-0 mt-3">
                                            {el.name}
                                        </div>
                                        <QuestionTooltip
                                            content={el.description || ''}
                                            error={false}
                                            className="w-full text-start" // 触发区域铺满，确保hover描述文字就触发
                                        >
                                            <div className="truncate max-w-[500px] text-[14px] text-[#5A5A5A] font-semibold">
                                                {el.description || ''}
                                            </div>
                                            <TooltipContent
                                                side="top" // 气泡在描述文字上方显示
                                                sideOffset={4}
                                                className="bg-primary/80 text-primary-foreground"
                                            >
                                                <div className="max-w-96 text-left break-all whitespace-normal">
                                                    {el.description || ''}
                                                </div>
                                            </TooltipContent>
                                        </QuestionTooltip>
                                    </div>
                                </div>
                            </TableCell>

                            <TableCell className="text-[#5A5A5A] flex: 1">{el.update_time.replace('T', ' ')}</TableCell>

                            <TableCell className="max-w-[300px] break-all text-[#5A5A5A] flex: 1">
                                <div className="truncate-multiline">{el.user_name || '--'}</div>
                            </TableCell>

                            {/* 操作列：修复「按钮移入行不高亮」 */}
                            <TableCell className="flex: 1 text-right hover:bg-transparent">
                                {/* 关键：hover:bg-transparent覆盖行的hover:bg-gray-50 */}
                                <div className="flex items-center justify-end gap-2">
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <button
                                                className="size-10 px-2 bg-transparent border-none shadow-none hover:bg-gray-300 flex items-center justify-center duration-200 relative"
                                                onClick={(e) => e.stopPropagation()}
                                            // 关键：stopPropagation防止触发父行onClick
                                            >
                                                <Ellipsis size={24} color="#a69ba2" strokeWidth={1.75} />
                                            </button>
                                        </DropdownMenuTrigger>

                                        <DropdownMenuContent
                                            align="end"
                                            className="rounded-md shadow-lg py-1 border-gray-200 z-[100] border border-transparent"
                                            style={{ backgroundColor: 'white', opacity: 1 }}
                                            onInteractOutside={() => setOpenMenus({})}
                                        >
                                            <DropdownMenuItem
                                                className={`flex items-center gap-2 px-4 py-2 ${(el.copiable || user.role === 'admin')
                                                    ? 'hover:bg-gray-100 cursor-pointer'
                                                    : 'text-gray-400 cursor-not-allowed'
                                                    }`}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    if (el.copiable || user.role === 'admin') {
                                                        handleDelete(el.id);
                                                    }
                                                }}
                                                disabled={!(el.copiable || user.role === 'admin')}
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
        <CreateModal datalist={datalist} open={open} setOpen={setOpen} onLoadEnd={setModelNameMap}></CreateModal>
        {/* <SelectData open={openData} setOpen={setOpenData} /> */}
    </div>
};
