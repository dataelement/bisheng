import { QaIcon } from "@/components/bs-icons/knowledge";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, SearchInput, Textarea } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/bs-ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import Tip from "@/components/bs-ui/tooltip/tip";
import { userContext } from "@/contexts/userContext";
import { copyQaDatabase, createFileLib, deleteFileLib, readFileLibDatabase, updateKnowledge } from "@/controllers/API";
import { getKnowledgeModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import { useTable } from "@/util/hook";
import { CircleAlert, Copy, Ellipsis, LoaderCircle, Settings, Trash2 } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useModel } from "../ModelPage/manage";

// Knowledge base status
const enum KnowledgeBaseStatus {
    Unpublished = 0,
    Published = 1,
    Copying = 2,
    Rebuilding = 3,
    Failed = 4
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
                toast({ variant: "error", description: t('loadModelError') });
            }
        };

        fetchModelData();
    }, [open, mode, currentLib]);

    useEffect(() => {
        if (!open) {
            setModelId('');
            setIsSubmitting(false);
            setIsModelChanged(false);
        }
    }, [open]);

    const { toast } = useToast()

    const handleCreate = async (e, isImport = false) => {
        const name = nameRef.current.value || '';
        let desc = descRef.current.value || '';

        const defaultDescPrefix = t('defaultDescPrefix');
        const defaultDescSuffix = t('defaultDescSuffix');
        const fixedTextLength = defaultDescPrefix.length + defaultDescSuffix.length;
        const maxNameLengthForDefaultDesc = 200 - fixedTextLength;

        if (!desc) {
            desc = name.length <= maxNameLengthForDefaultDesc
                ? `${defaultDescPrefix}${name}${defaultDescSuffix}`
                : '';
        }

        if (!name) {
            toast({ variant: 'error', description: t('lib.enterLibraryName') });
            return;
        }
        if (name.length > 200) {
            toast({ variant: 'error', description: t('nameExceedsLimit') });
            return;
        }
        const isEditMode = mode === 'edit' && currentLib;
        const nameUnchanged = isEditMode && name === currentLib.name;
        if (!nameUnchanged && datalist.find(data => data.name === name && (!currentLib || data.id !== currentLib.id))) {
            toast({ variant: 'error', description: t('lib.nameExists') });
            return;
        }
        if (descRef.current.value && desc.length > 200) {
            toast({ variant: 'error', description: t('lib.descriptionLimit') });
            return;
        }

        setIsSubmitting(true);
        try {
            if (mode === 'create') {
                await captureAndAlertRequestErrorHoc(createFileLib({
                    name,
                    description: desc,
                    model: modelId,
                    type: 1
                }).then((res) => {
                    window.libname = [name, desc];
                    navigate(isImport ? `/filelib/qalib/upload/${res.id}` : `/filelib/qalib/${res.id}`);
                    onOpenChange(false);
                })).finally(() => {
                    setIsSubmitting(false)
                });

            } else {
                await updateKnowledge({
                    model_id: modelId,
                    model_type: "embedding",
                    knowledge_id: currentLib.id,
                    knowledge_name: name,
                    description: desc
                });
                toast({ variant: "success", description: t('updateSuccess') });
                onOpenChange(false);
                onLoadEnd();
            }
        } catch (error) {
            if (error) {
                toast({ variant: "error", description: error || t('operationFailed') });
            } else {
                toast({ variant: "error", description: mode === 'create' ? t('createFailed') : t('updateFailed') });
            }
        } finally {
            setIsSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{mode === 'create' ? t('lib.createLibrary') : t('knowledgeSettings')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    {mode === 'edit' && currentLib && (
                        <div className="space-y-4">
                            <div className="flex items-center gap-48">
                                <label className="bisheng-label text-sm text-gray-500">{t('lib.knowledgeBaseId')}</label>
                                <div className="text-sm">{currentLib.id}</div>
                            </div>
                            <div className="flex items-center gap-48">
                                <label className="bisheng-label text-sm text-gray-500">{t('createTime')}</label>
                                <div className="text-sm">{currentLib.create_time.replace('T', ' ')}</div>
                            </div>
                        </div>
                    )}
                    <div className="">
                        <label htmlFor="name" className="bisheng-label">{t('lib.libraryName')}</label>
                        <span className="text-red-500">*</span>
                        <Input
                            name="name"
                            ref={nameRef}
                            placeholder={t('lib.enterLibraryName')}
                            className="col-span-3"
                        />
                    </div>
                    <div className="">
                        <label htmlFor="desc" className="bisheng-label">{t('knowledgeDesc')}</label>
                        <Textarea
                            id="desc"
                            ref={descRef}
                            placeholder={t('pleaseEnterDesc')}
                            rows={8}
                            className="col-span-3"
                        />
                    </div>
                    <div className="">
                        <label htmlFor="model" className="bisheng-label">{t('embeddingModel')}</label>
                        {isLoading ? (
                            <div className="flex items-center gap-2 p-3 border rounded-md bg-gray-50">
                                <LoadIcon className="w-4 h-4 animate-spin" />
                                <span className="text-sm text-gray-600">{t('loadingModelList')}</span>
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
                                {t('noAvailableModel')}
                            </div>
                        )}
                        {mode === 'edit' && isModelChanged && (
                            <p className="text-red-500 text-sm mt-1 flex items-center gap-1">
                                <CircleAlert className="w-4 h-4" color="#ef4444" />
                                {t('embeddingModelWarning')}
                            </p>
                        )}
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11">{t('cancel')}</Button>
                    </DialogClose>
                    {mode === 'create' ? (
                        <>
                            <Button
                                type="submit"
                                className="px-11 flex"
                                onClick={(e) => handleCreate(e, false)}
                                disabled={isSubmitting}
                            >
                                {isSubmitting && <LoadIcon className="mr-1" />}
                                {t('completeCreation')}
                            </Button>
                            {/* <Button
                                type="submit"
                                className="px-8 h-8 flex"
                                onClick={(e) => handleCreate(e, true)}
                                disabled={isSubmitting}
                            >
                                {isSubmitting && <LoadIcon className="mr-1" />}
                                {t('createImport')}
                            </Button> */}
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
    );
}

const doing = {};
export default function KnowledgeQa(params) {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);
    const { toast } = useToast();
    const navigate = useNavigate();
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [currentSettingLib, setCurrentSettingLib] = useState(null);
    const [copyLoadingId, setCopyLoadingId] = useState<string | null>(null);
    const [selectOpenId, setSelectOpenId] = useState<string | null>(null);
    const [modalKey, setModalKey] = useState(0);

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable(
        { cancelLoadingWhenReload: true },
        (param) => readFileLibDatabase({ ...param, name: param.keyword, type: 1 })
    );

    useEffect(() => {
        const todos = datalist.filter(lib => lib.state === KnowledgeBaseStatus.Copying);
        todos.forEach(lib => {
            if (doing[lib.id] && datalist.find(item => item.id === lib.id && item.state !== KnowledgeBaseStatus.Copying)) {
                toast({ variant: 'success', description: t('copyCompleted', { name: lib.name }) });
                delete doing[lib.id];
            }
        });

        const timer = todos.length > 0 ? setTimeout(reload, 5000) : null;
        return () => clearTimeout(timer);
    }, [datalist]);

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('lib.confirmDeleteLibrary'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFileLib(id).then(reload));
                next();
            },
        });
    };

    const handleOpenSettings = (lib) => {
        const newCurrentLib = JSON.parse(JSON.stringify(lib));
        newCurrentLib.__updateKey = Date.now();

        setCurrentSettingLib(newCurrentLib);
        setSettingsOpen(true);
        setModalKey(prev => prev + 1);
        setSelectOpenId(null);
    };

    const handleSettingsClose = (isOpen) => {
        setSettingsOpen(isOpen);
        if (!isOpen) {
            setCurrentSettingLib(null);
        }
    };

    const handleCachePage = () => {
        window.LibPage = { page, type: 'qa' };
    };

    useEffect(() => {
        const _page = window.LibPage;
        if (_page) {
            setPage(_page.page);
            delete window.LibPage;
        } else {
            setPage(1);
        }
    }, []);

    const { t } = useTranslation('knowledge');

    const handleCopy = async (elem) => {
        const newName = t('copyOf', { name: elem.name });
        if (newName.length > 200) {
            toast({ variant: 'error', description: t('copyNameExceedsLimit') });
            setSelectOpenId(null);
            return;
        }

        setCopyLoadingId(elem.id);
        doing[elem.id] = true;

        try {
            await captureAndAlertRequestErrorHoc(copyQaDatabase(elem.id));
            reload();
        } catch (error) {
            toast({ variant: 'error', description: t('copyFailed') });
        } finally {
            setCopyLoadingId(null);
            setSelectOpenId(null);
        }
    };

    return (
        <div className="relative">
            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
            )}
            <div className="h-[calc(100vh-128px)] overflow-y-auto pb-20">
                <div className="flex justify-end gap-4 items-center absolute right-0 top-[-44px]">
                    <SearchInput placeholder={t('lib.searchPlaceholder', { ns: 'bs' })} onChange={(e) => search(e.target.value)} />
                    <Button className="px-8 text-[#FFFFFF]" onClick={() => setOpen(true)}>{t('create')}</Button>
                </div>
                <Table>
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
                                onClick={() => {
                                    if ([KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state)) return;
                                    window.libname = [el.name, el.description];
                                    navigate(`/filelib/qalib/${el.id}`);
                                    handleCachePage();
                                }}
                            >
                                <TableCell className="font-medium max-w-[280px]">
                                    <div className="flex items-center gap-2">
                                        <div className="flex items-center justify-center size-12 text-white rounded-[4px] w-[40px] h-[40px]">
                                            <QaIcon className="text-primary size-10" />
                                        </div>
                                        <div>
                                            <div className="truncate max-w-[500px] w-[264px] text-[14px] font-medium pt-2">
                                                {el.name}
                                            </div>
                                            <QuestionTooltip
                                                content={el.description || ''}
                                                error={false}
                                                className="w-full text-start"
                                            >
                                                <div className="truncate max-w-[400px] text-[12px] text-[#5A5A5A] pt-1">
                                                    {el.description || ''}
                                                </div>
                                            </QuestionTooltip>
                                        </div>
                                    </div>
                                </TableCell>
                                <TableCell className="text-[#5A5A5A]">
                                    {el.update_time.replace('T', ' ')}
                                </TableCell>
                                <TableCell className="max-w-[300px] break-all">
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
                                                    setSelectOpenId(null);
                                                }
                                            }}
                                            onValueChange={(selectedValue) => {
                                                setSelectOpenId(null);
                                                switch (selectedValue) {
                                                    case 'copy':
                                                        el.state === KnowledgeBaseStatus.Published && handleCopy(el);
                                                        break;
                                                    case 'set':
                                                        handleOpenSettings(el);
                                                        break;
                                                    case 'delete':
                                                        (el.copiable || user.role === 'admin') && handleDelete(el.id);
                                                        break;
                                                }
                                            }}
                                        >
                                            <SelectTrigger
                                                showIcon={false}
                                                disabled={copyLoadingId === el.id}
                                                onClick={(e) => e.stopPropagation()}
                                                className="size-10 px-2 bg-transparent border-none shadow-none hover:bg-gray-300 flex items-center justify-center duration-200 relative"
                                            >
                                                {[KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state) ? (
                                                    <>
                                                        <LoaderCircle className="animate-spin" />
                                                        <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 bg-white text-gray-800 text-xs px-2 py-1 rounded whitespace-nowrap border border-gray-300 shadow-sm">
                                                            {t('copying')}
                                                        </div>
                                                    </>
                                                ) : (
                                                    <Ellipsis size={24} color="#a69ba2" strokeWidth={1.75} />
                                                )}
                                            </SelectTrigger>
                                            <SelectContent
                                                onClick={(e) => e.stopPropagation()}
                                                className="z-50 overflow-visible"
                                            >
                                                <Tip content={!el.copiable && t('noPermission')} side='top'>
                                                    <SelectItem
                                                        showIcon={false}
                                                        value="copy"
                                                        disabled={!(el.copiable || user.role === 'admin') || el.state !== KnowledgeBaseStatus.Published || copyLoadingId === el.id}
                                                    >
                                                        <div className="flex gap-2 items-center">
                                                            <Copy className="w-4 h-4" />
                                                            {t('lib.copy')}
                                                        </div>
                                                    </SelectItem>
                                                </Tip>
                                                <Tip content={!el.copiable && t('noPermission')} side='top'>
                                                    <SelectItem
                                                        value="set"
                                                        disabled={!el.copiable}
                                                        showIcon={false}
                                                    >
                                                        <div className="flex gap-2 items-center">
                                                            <Settings className="w-4 h-4" />
                                                            {t('setting')}
                                                        </div>
                                                    </SelectItem>
                                                </Tip>
                                                <Tip content={!el.copiable && t('noPermission')} side='top'>
                                                    <SelectItem
                                                        value="delete"
                                                        showIcon={false}
                                                        disabled={!(el.copiable || user.role === 'admin')}
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

            {/* Create modal */}
            <CreateModal
                datalist={datalist}
                open={open}
                onOpenChange={setOpen}
                onLoadEnd={() => { }}
                mode="create"
            />

            {/* Settings modal */}
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