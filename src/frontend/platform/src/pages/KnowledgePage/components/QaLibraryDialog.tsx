import { Button, Input, Textarea, notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";


import { createFileLib, updateKnowledge } from "@/controllers/API";
import { getKnowledgeModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ModelSelect } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useModel } from "../../ModelPage/manage";
interface LibraryDialogProps {
    datalist: { id: string | number; name: string }[]
    open: boolean
    onOpenChange: (open: boolean) => void
    onLoadEnd: () => void
    mode?: 'create' | 'edit'
    currentLib?: { id: string | number; name: string; description?: string; model?: string | number; create_time?: string } | null
}

export function QaLibraryDialog({ datalist, open, onOpenChange, onLoadEnd, mode = 'create', currentLib = null }: LibraryDialogProps) {
    const { t } = useTranslation('knowledge')

    const navigate = useNavigate()
    const nameRef = useRef<HTMLInputElement>(null)
    const descRef = useRef<HTMLTextAreaElement>(null)
    const [modelId, setModelId] = useState<string | number>('')

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
                    setModelId(currentLib?.model ?? '');
                }

                if (mode === 'edit' && currentLib) {
                    // Use setTimeout to ensure DOM has been rendered
                    setTimeout(() => {
                        if (nameRef.current) nameRef.current!.value = currentLib.name || '';
                        if (descRef.current) descRef.current!.value = currentLib.description || '';
                    }, 0);
                }
            } catch (error) {
                console.error('Failed to load model data:', error);
                notification.open({ type: "error", description: String(t('loadModelError') ?? '') });
            }
        };

        fetchModelData();
    }, [open, mode, currentLib, t]);

    useEffect(() => {
        if (!open) {
            setModelId('');
            setIsSubmitting(false);
            setIsModelChanged(false);
        }
    }, [open]);


    const handleCreate = async (isImport = false) => {
        const name = nameRef.current!.value || '';
        let desc = descRef.current!.value || '';

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
            notification.open({ type: 'error', description: String(t('lib.enterLibraryName', { ns: 'bs' }) ?? '') });
            return;
        }
        if (name.length > 200) {
            notification.open({ type: 'error', description: String(t('nameExceedsLimit') ?? '') });
            return;
        }
        const isEditMode = mode === 'edit' && currentLib;
        const nameUnchanged = isEditMode && name === currentLib.name;
        if (!nameUnchanged && datalist.find(data => data.name === name && (!currentLib || data.id !== currentLib.id))) {
            notification.open({ type: 'error', description: String(t('lib.nameExists') ?? '') });
            return;
        }
        if (descRef.current!.value && desc.length > 200) {
            notification.open({ type: 'error', description: String(t('lib.descriptionLimit', { ns: 'bs' }) ?? '') });
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
                }).then((response) => {
                    const res = response as unknown as { id: string | number };
                    (window as Window & { libname?: [string, string] }).libname = [name, desc];
                    navigate(isImport ? `/filelib/qalib/upload/${res.id}` : `/filelib/qalib/${res.id}`);
                    onOpenChange(false);
                })).finally(() => {
                    setIsSubmitting(false)
                });

            } else {
                await updateKnowledge({
                    model_id: modelId,
                    model_type: "embedding",
                    knowledge_id: currentLib!.id,
                    knowledge_name: name,
                    description: desc
                });
                notification.open({ type: "success", description: String(t('updateSuccess') ?? '') });
                onOpenChange(false);
                onLoadEnd();
            }
        } catch (error) {
            if (error) {
                notification.open({ type: "error", description: String(error || t('operationFailed')) });
            } else {
                notification.open({ type: "error", description: String(mode === 'create' ? t('createFailed') : t('updateFailed') ?? '') });
            }
        } finally {
            setIsSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{mode === 'create' ? t('lib.createLibrary', { ns: 'bs' }) : t('knowledgeSettings', { ns: 'bs' })}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    {mode === 'edit' && currentLib && (
                        <div className="space-y-4">
                            <div className="flex items-center gap-48">
                                <label className="bisheng-label text-sm text-gray-500">{t('lib.knowledgeBaseId', { ns: 'bs' })}</label>
                                <div className="text-sm">{currentLib.id}</div>
                            </div>
                            <div className="flex items-center gap-48">
                                <label className="bisheng-label text-sm text-gray-500">{t('createTime', { ns: 'bs' })}</label>
                                <div className="text-sm">{(currentLib.create_time || '').replace('T', ' ')}</div>
                            </div>
                        </div>
                    )}
                    <div className="">
                        <label htmlFor="name" className="bisheng-label">{t('system.libraryName', { ns: 'bs' })}</label>
                        <span className="text-red-500">*</span>
                        <Input name="name" ref={nameRef} placeholder={t('lib.enterLibraryName', { ns: 'bs' })} className={"col-span-3"} />
                    </div>
                    <div className="">
                        <label htmlFor="desc" className="bisheng-label">{t('knowledgeDesc')}</label>
                        <Textarea id="desc" ref={descRef} placeholder={t('pleaseEnterDesc')} rows={8} textareaClassName={"col-span-3"} />
                    </div>
                    <div className="">
                        <label htmlFor="model" className="bisheng-label">{t('embeddingModel')}</label>
                        {isLoading ? (
                            <div className="flex items-center gap-2 p-3 border rounded-md bg-gray-50">
                                <Outlined.Loading className="animate-spin w-4 h-4 animate-spin" />
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
                                <Outlined.Attention className="w-4 h-4" color="#ef4444" />
                                {t('embeddingModelWarning')}
                            </p>
                        )}
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outlined" className="px-11" color="default">{t('cancel')}</Button>
                    </DialogClose>
                    {mode === 'create' ? (
                        <>
                            <Button type="submit" className="px-11 flex" onClick={() => handleCreate(false)} disabled={isSubmitting}>
                                {isSubmitting && <Outlined.Loading className="animate-spin mr-1" />}
                                {t('completeCreation')}
                            </Button>
                            {/* <Button
                                type="submit"
                                className="px-8 h-8 flex"
                                onClick={() => handleCreate(true)}
                                disabled={isSubmitting}
                            >
                                {isSubmitting && <Outlined.Loading className="animate-spin mr-1" />}
                                {t('createImport')}
                            </Button> */}
                        </>
                    ) : (
                        <Button type="submit" className="px-8 h-8 flex" onClick={() => handleCreate(false)} disabled={isSubmitting}>
                            {isSubmitting && <Outlined.Loading className="animate-spin mr-1" />}
                            {t('confirm')}
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
