import { useNavigate } from "react-router-dom";
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

import { BookIcon } from "@/components/bs-icons/knowledge";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/bs-ui/select";
import { toast, useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import Tip from "@/components/bs-ui/tooltip/tip";
import { getKnowledgeModelConfig } from "@/controllers/API/finetune";
import { CircleAlert, Copy, Ellipsis, LoaderCircle, Settings, Trash2 } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Textarea } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { userContext } from "../../contexts/userContext";
import { copyLibDatabase, createFileLib, deleteFileLib, readFileLibDatabase, updateKnowledge } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useTable } from "../../util/hook";
import { useModel } from "../ModelPage/manage";
import { ModelSelect } from "../ModelPage/manage/tabs/WorkbenchModel";

// Knowledge base status
const enum KnowledgeBaseStatus {
    Unpublished = 0,
    Published = 1,   // Document knowledge base build success status
    Copying = 2,
    Rebuilding = 3,  // Document knowledge base rebuilding status
    Failed = 4       // Document knowledge base rebuild failed status
}

function CreateModal({ datalist, open, onOpenChange, onLoadEnd, mode = 'create', currentLib = null }) {
    const { t } = useTranslation('knowledge')
    const navigate = useNavigate()

    const nameRef = useRef(null)
    const descRef = useRef(null)
    const [modelId, setModelId] = useState('')

    const [isSubmitting, setIsSubmitting] = useState(false)
    const [isModelChanged, setIsModelChanged] = useState(false)

    const { embeddings, isLoading } = useModel()
    // Unified handling of model data fetching
    useEffect(() => {
        if (!open) return;

        const fetchModelData = async () => {
            try {
                if (mode === 'create') {
                    const config = await getKnowledgeModelConfig();
                    setModelId(config.embedding_model_id);
                } else {
                    setModelId(currentLib.model);
                }

                if (mode === 'edit' && currentLib) {
                    // Use setTimeout to ensure DOM has been rendered
                    setTimeout(() => {
                        if (nameRef.current) nameRef.current.value = currentLib.name || '';
                        if (descRef.current) descRef.current.value = currentLib.description || '';
                    }, 0);
                }
            } catch (error) {
                console.error('Failed to load model data:', error);
                toast({
                    variant: "error",
                    description: t('loadModelError')
                });
            }
        };

        fetchModelData();
    }, [open, mode, currentLib]);

    useEffect(() => {
        // Clear all internal state when modal closes
        if (!open) {
            setModelId('');
            setIsSubmitting(false);
            setIsModelChanged(false);
            setError({ name: false, desc: false });
        }
    }, [open]);

    const { toast } = useToast()
    const [error, setError] = useState({ name: false, desc: false })

    const handleCreate = async (e, isImport = false) => {
        const name = nameRef.current.value || ''; // Name (default empty string to avoid null)
        let desc = descRef.current.value || '';   // Description (default empty string)

        // 1. Define the fixed text part of the default description (excluding name)
        const defaultDescPrefix = t('defaultDescPrefix');
        const defaultDescSuffix = t('defaultDescSuffix');
        // Fixed text total length = prefix length + suffix length
        const fixedTextLength = defaultDescPrefix.length + defaultDescSuffix.length;
        // Maximum name length allowed = 200 - fixed text length (ensure name + fixed text ≤ 200)
        const maxNameLengthForDefaultDesc = 200 - fixedTextLength;

        // 2. When description is not entered, generate default description (strictly control total length ≤ 200)
        if (!desc) {
            // Case 1: Name length ≤ maximum allowable length → directly concatenate to generate default description
            if (name.length <= maxNameLengthForDefaultDesc) {
                desc = `${defaultDescPrefix}${name}${defaultDescSuffix}`;
            }
            // Case 2: Name length > maximum allowable length → truncate name then concatenate
            else {
                desc = '';
            }
        }

        // 3. Original validation logic (only for user-entered descriptions, default description already ensures ≤ 200)
        if (!name) {
            handleError(t('lib.enterLibraryName'));
            return;
        }
        if (name.length > 200) {
            handleError(t('nameExceedsLimit'));
            return;
        }


        // Fix: Name duplication validation logic
        // In edit mode and name unchanged, skip duplication check
        const isEditMode = mode === 'edit' && currentLib;
        const nameUnchanged = isEditMode && name === currentLib.name;

        if (!nameUnchanged && datalist.find(data => data.name === name && (!currentLib || data.id !== currentLib.id))) {
            handleError(t('lib.nameExists',{ns:'bs'}));
            return;
        }

        // 仅校验用户手动输入的描述（默认描述已控制长度，可跳过）
        if (descRef.current.value && desc.length > 200) {
            handleError(t('lib.descriptionLimit'));
            return;
        }

        setIsSubmitting(true)
        if (mode === 'create') {
            await captureAndAlertRequestErrorHoc(createFileLib({
                name,
                description: desc,
                model: modelId,
                type: 0
            }).then(res => {
                window.libname = [name, desc]
                navigate(isImport
                    ? `/filelib/upload/${res.id}`
                    : `/filelib/${res.id}`
                );
                onOpenChange(false); // 修复：用onOpenChange关闭弹窗
            })).finally(() => {
                setIsSubmitting(false)
            })
        } else {
            const data = {
                "model_id": modelId,
                "model_type": "embedding",
                "knowledge_id": currentLib.id,
                "knowledge_name": name,
                "description": desc
            }
            await captureAndAlertRequestErrorHoc(updateKnowledge(data).then(res => {
                toast({
                    variant: "success",
                    description: '更新成功'
                })
                onOpenChange(false); // 修复：用onOpenChange关闭弹窗（替代原setOpen）
                onLoadEnd()
            }).catch(error => {
                toast({ variant: "error", description: error || '更新失败，请重试' });
                onOpenChange(false); // 错误时也关闭弹窗，避免状态卡住
            })).finally(() => {
                setIsSubmitting(false)
            })
        }
    }

    const handleError = (message) => {
        toast({
            variant: 'error',
            description: message
        });
    }

    return <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{mode === 'create' ? t('lib.createLibrary',{ ns: 'bs' }) : '知识库设置'}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-2">
                {mode === 'edit' && currentLib && (
                    <div className="space-y-4">
                        <div className="flex items-center gap-48">
                            <label className="bisheng-label text-sm text-gray-500">{t('lib.knowledgeBaseId',{ns:'bs'})}</label>
                            <div className="text-sm">{currentLib.id}</div>
                        </div>
                        <div className="flex items-center gap-48">
                            <label className="bisheng-label text-sm text-gray-500">{t('createTime',{ ns: 'bs' })}</label>
                            <div className="text-sm">
                                {currentLib.create_time.replace('T', ' ')}
                            </div>
                        </div>
                    </div>
                )}
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('lib.libraryName',{ ns: 'bs' })}</label>
                    <span className="text-red-500">*</span>
                    <Input
                        name="name"
                        ref={nameRef}
                        defaultValue={mode === 'edit' && currentLib ? currentLib.name : ''}
                        placeholder={t('lib.enterLibraryName',{ ns: 'bs' })}
                        className={`col-span-3 ${error.name && 'border-red-400'}`}
                    />
                </div>
                <div className="">
                    <label htmlFor="desc" className="bisheng-label">知识库描述</label>
                    <Textarea
                        id="desc"
                        ref={descRef}
                        defaultValue={mode === 'edit' && currentLib ? currentLib.description : ''}
                        placeholder="请输入知识库描述"
                        rows={8}
                        className={`col-span-3 ${error.desc && 'border-red-400'}`}
                    />
                </div>
                <div className="">
                    <label htmlFor="model" className="bisheng-label">知识库embedding模型选择</label>
                    {isLoading ? (
                        <div className="flex items-center gap-2 p-3 border rounded-md bg-gray-50">
                            <LoadIcon className="w-4 h-4 animate-spin" />
                            <span className="text-sm text-gray-600">正在加载模型列表...</span>
                        </div>
                    ) : embeddings.length > 0 ? (
                        <ModelSelect
                            key={`model-select-${modelId}`}
                            label=""
                            close
                            value={modelId}
                            options={embeddings}
                            onChange={(modelId) => {
                                setModelId(modelId);
                                if (mode === 'edit') setIsModelChanged(true);
                            }}
                        />
                    ) : (
                        <div className="p-3 border rounded-md bg-gray-50 text-sm text-gray-600">
                            暂无可用模型
                        </div>
                    )}
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
                {mode === 'create' ? (
                    <>
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
                            {t('createImport',{ ns: 'bs' })}
                        </Button>
                    </>
                ) : (
                    <Button
                        type="submit"
                        className="px-8 h-8 flex"
                        onClick={(e) => handleCreate(e, false)}
                        disabled={isSubmitting}
                    >
                        {isSubmitting && <LoadIcon className="mr-1" />}
                        {t('confirm')}
                    </Button>
                )}
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

const doing = {} // 记录copy中的知识库
export default function KnowledgeFile() {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);
    const { message } = useToast()
    const navigate = useNavigate()
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [currentSettingLib, setCurrentSettingLib] = useState(null);
    const [copyLoadingId, setCopyLoadingId] = useState<string | null>(null);
    // 新增：控制Select下拉状态，避免偶发不弹出
    const [selectOpenId, setSelectOpenId] = useState<string | null>(null);
    const [modalKey, setModalKey] = useState(0); // 新增：用于强制重新渲染弹窗

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({ cancelLoadingWhenReload: true }, (param) =>
        readFileLibDatabase({ ...param, name: param.keyword })
    )

    // 复制中开启轮询
    useEffect(() => {
        const todos = datalist.reduce((prev, curr) => {
            if (curr.state === KnowledgeBaseStatus.Copying) {
                prev.push({ id: curr.id, name: curr.name })
            }
            return prev
        }, [])

        todos.map(todo => {
            if (doing[todo.id]) {
                const lib = datalist.find(item => item.id === todo.id);
                if (lib && lib.state !== KnowledgeBaseStatus.Copying) {
                    message({
                        variant: 'success',
                        description: `${todo.name} 复制完成`
                    })
                    delete doing[todo.id]
                }
            }
        })

        let timer = null
        if (todos.length > 0) {
            timer = setTimeout(() => {
                reload()
            }, 5000);
        }

        return () => {
            clearTimeout(timer)
        }
    }, [datalist])

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('lib.confirmDeleteLibrary',{ ns: 'bs' }),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFileLib(id).then(res => {
                    reload();
                }));
                next()
            },
        })
    }

    const handleOpenSettings = (lib) => {
        console.log("=== handleOpenSettings 开始执行 ===");
        console.log("当前点击的lib ID:", lib.id);
        // 1. 深拷贝：彻底断开与原 lib 的引用关联（解决嵌套属性引用不变问题）
        const newCurrentLib = JSON.parse(JSON.stringify(lib));
        // 2. 注入唯一标识：即使数据完全相同，也让 currentSettingLib 引用绝对唯一
        newCurrentLib.__updateKey = Date.now(); // 每次点击生成不同的时间戳

        setCurrentSettingLib(newCurrentLib); // 此时传递的是完全新的对象引用
        setSettingsOpen(true);
        setModalKey(prev => prev + 1); // 保留 modalKey 确保弹窗重新挂载
        console.log("handleOpenSettings called with lib:", newCurrentLib); // 验证打印
    };

    const handleSettingsClose = (isOpen) => {
        console.log("handleSettingsClose called with isOpen:", isOpen);
        setSettingsOpen(isOpen);
        if (!isOpen) {
            setCurrentSettingLib(null);
            setSelectOpenId(null);
            console.log("Settings modal closed and state cleared");
        }
    };

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

    const { t, i18n } = useTranslation('knowledge');
    useEffect(() => {
        i18n.loadNamespaces('knowledge');
    }, [i18n]);

    // copy
    const handleCopy = async (elem) => {
        const newName = `${elem.name}的副本`;
        if (newName.length > 200) {
            toast({
                title: '操作失败',
                variant: 'error',
                description: '复制后的知识库名称超过字数限制'
            });

            // 重置所有相关状态
            setSelectOpenId(null);
            setCopyLoadingId(null);

            // 强制重新渲染 Select 组件
            setModalKey(prev => prev + 1);
            return;
        }

        setCopyLoadingId(elem.id);
        doing[elem.id] = true;

        try {
            await captureAndAlertRequestErrorHoc(copyLibDatabase(elem.id));
            reload();
        } catch (error) {
            message({
                variant: 'error',
                description: '复制失败'
            });
        } finally {
            setCopyLoadingId(null);
            setSelectOpenId(null);
            // 确保 Select 组件重置
            setModalKey(prev => prev + 1);
        }
    }

    useEffect(() => {
        console.log("settingsOpen state changed:", settingsOpen);
        console.log("currentSettingLib:", currentSettingLib);
        console.log("modalKey:", modalKey);
    }, [settingsOpen, currentSettingLib, modalKey]);

    return (
        <div className="relative">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}
            <div className="h-[calc(100vh-128px)] overflow-y-auto pb-20">
                <div className="flex justify-end gap-4 items-center absolute right-0 top-[-44px]">
                    <SearchInput placeholder={t('lib.searchPlaceholder', { ns: 'bs' })} onChange={(e) => search(e.target.value)} />
                    <Button className="px-8 text-[#FFFFFF]" onClick={() => setOpen(true)}>{t('create', { ns: 'bs' })}</Button>
                </div>
                <Table noScroll>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('lib.libraryName', { ns: 'bs' })}</TableHead>
                            <TableHead>{t('updateTime')}</TableHead>
                            <TableHead>{t('lib.createUser', { ns: 'bs' })}</TableHead>
                            <TableHead className="text-right">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el: any) => (
                            <TableRow
                                key={el.id}
                                className=""
                                onClick={() => {
                                    if ([KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state)) return;
                                    window.libname = [el.name, el.description];
                                    navigate(`/filelib/${el.id}`);
                                    handleCachePage();
                                }}
                            >
                                <TableCell
                                    className="font-medium max-w-[200px]"
                                >
                                    <div className="flex items-center gap-2">
                                        <div className="flex items-center justify-center size-12 text-white rounded-[4px]  w-[40px] h-[40px]">
                                            {/* <BookCopy  className="size-5"/> */}
                                            <BookIcon className="text-primary size-10" />
                                        </div>
                                        <div>
                                            <div className="truncate max-w-[500px] w-[264px] text-[14px] font-medium pt-2 flex items-center gap-2">
                                                {el.name}
                                            </div>
                                            <QuestionTooltip
                                                content={el.description || ''}
                                                error={false}
                                                className="w-full text-start"
                                            >
                                                <div className="truncate max-w-[500px] text-[12px] text-[#5A5A5A] pt-1">
                                                    {el.description || ''}
                                                </div>
                                            </QuestionTooltip>
                                        </div>
                                    </div>
                                </TableCell>

                                <TableCell
                                    className="text-[#5A5A5A]"
                                >
                                    {el.update_time.replace('T', ' ')}
                                </TableCell>

                                <TableCell
                                    className="max-w-[300px] break-all"
                                >
                                    <div className="truncate-multiline text-[#5A5A5A]">{el.user_name || '--'}</div>
                                </TableCell>

                                <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-2">
                                        <Select
                                            key={`${el.id}-${modalKey}`}
                                            open={selectOpenId === el.id}
                                            onOpenChange={(isOpen) => {
                                                if (el.state === 2 || el.state === 0) return;
                                                if (copyLoadingId !== el.id) {
                                                    setSelectOpenId(isOpen ? el.id : null);
                                                } else if (!isOpen) {
                                                    // 如果是复制中状态且要关闭，允许关闭
                                                    setSelectOpenId(null);
                                                }
                                            }}
                                            onValueChange={(selectedValue) => {
                                                setSelectOpenId(null);
                                                console.log("Selected value:", selectedValue, "for lib:", el.id);

                                                switch (selectedValue) {
                                                    case 'copy':
                                                        el.state === KnowledgeBaseStatus.Published && handleCopy(el);
                                                        break;
                                                    case 'set':
                                                        handleOpenSettings(el);
                                                        break;
                                                    case 'delete':
                                                        el.copiable && handleDelete(el.id);
                                                        break;
                                                }
                                            }}
                                        >
                                            <SelectTrigger
                                                showIcon={false}
                                                disabled={copyLoadingId === el.id}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                }}
                                                className="size-10 px-2 bg-transparent border-none shadow-none hover:bg-gray-300 flex items-center justify-center duration-200 relative"
                                            >
                                                {[KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state) ? (
                                                    <>
                                                        <LoaderCircle className="animate-spin" />
                                                        <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 bg-white text-gray-800 text-xs px-2 py-1 rounded whitespace-nowrap border border-gray-300 shadow-sm">
                                                            复制中
                                                        </div>
                                                    </>
                                                ) : (
                                                    <Ellipsis size={24} color="#a69ba2" strokeWidth={1.75} />
                                                )}
                                            </SelectTrigger>
                                            <SelectContent
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                }}
                                                className="z-50 overflow-visible"
                                            >
                                                <Tip content={!el.copiable && '暂无操作权限'} side='top'>
                                                    <SelectItem
                                                        showIcon={false}
                                                        value="copy"
                                                        className="data-[disabled]:pointer-events-auto"
                                                        disabled={!(el.copiable || user.role === 'admin') || el.state !== KnowledgeBaseStatus.Published || copyLoadingId === el.id}
                                                    >
                                                        <div className="flex gap-2 items-center" >
                                                            <Copy className="w-4 h-4" />
                                                            {t('lib.copy',{ ns: 'bs' })}
                                                        </div>
                                                    </SelectItem>
                                                </Tip>
                                                <Tip content={!el.copiable && '暂无操作权限'} side='top'>
                                                    <SelectItem
                                                        value="set"
                                                        disabled={!el.copiable}
                                                        className="data-[disabled]:pointer-events-auto"
                                                        showIcon={false}
                                                    >
                                                        <div className="flex gap-2 items-center">
                                                            <Settings className="w-4 h-4" />
                                                            {t('设置')}
                                                        </div>
                                                    </SelectItem>
                                                </Tip>
                                                <Tip content={!el.copiable && '暂无操作权限'} side='top'>
                                                    <SelectItem
                                                        value="delete"
                                                        showIcon={false}
                                                        className="data-[disabled]:pointer-events-auto"
                                                        disabled={!el.copiable}
                                                    >
                                                        <div className="flex gap-2 items-center">
                                                            <Trash2 className="w-4 h-4" />
                                                            {t('delete')}
                                                        </div>
                                                    </SelectItem>
                                                </Tip>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            <div className="bisheng-table-footer px-6 bg-background-login">
                <p className="desc">{t('lib.libraryCollection', { ns: 'bs' })}</p>
                <div>
                    <AutoPagination
                        page={page}
                        pageSize={pageSize}
                        total={total}
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>

            {/* 创建弹窗 */}
            <CreateModal
                datalist={datalist}
                open={open}
                onOpenChange={setOpen}
                onLoadEnd={() => { }}
                mode="create"
            />

            {/* 编辑（设置）弹窗 - 使用 key 强制重新渲染 */}
            {settingsOpen && (
                <CreateModal
                    key={`settings-modal-${modalKey}`}
                    datalist={datalist}
                    open={settingsOpen}
                    onOpenChange={handleSettingsClose}
                    onLoadEnd={reload}
                    mode="edit"
                    currentLib={currentSettingLib}
                />
            )}
        </div>
    );
}