import { Button, Input, Textarea, notification } from '@bisheng/ui';
import { Dialog,DialogClose,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { getKnowledgeModelConfig } from "@/controllers/API/finetune";
import { Outlined } from "bisheng-icons";
import { useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";


import { createFileLib,updateKnowledge } from "../../../controllers/API";
import { showApiError } from "../../../controllers/request";
import { useModel } from "../../ModelPage/manage";
import { ModelSelect } from "../../ModelPage/manage/tabs/WorkbenchModel";
interface LibraryDialogProps {
    datalist: { id: string | number; name: string }[]
    open: boolean
    onOpenChange: (open: boolean) => void
    onLoadEnd: () => void
    mode?: 'create' | 'edit'
    currentLib?: { id: string | number; name: string; description?: string; model?: string | number; create_time?: string } | null
}

export function KnowledgeLibraryDialog({ datalist, open, onOpenChange, onLoadEnd, mode = 'create', currentLib = null }: LibraryDialogProps) {
    const { t } = useTranslation('knowledge')

    const navigate = useNavigate()

    const nameRef = useRef<HTMLInputElement>(null)
    const descRef = useRef<HTMLTextAreaElement>(null)
    const [modelId, setModelId] = useState<string | number>('')

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
        // Clear all internal state when modal closes
        if (!open) {
            setModelId('');
            setIsSubmitting(false);
            setIsModelChanged(false);
            setError({ name: false, desc: false });
        }
    }, [open]);

    const [error, setError] = useState({ name: false, desc: false })

    const handleCreate = async (isImport = false) => {
        const name = nameRef.current!.value || ''; // Name (default empty string to avoid null)
        let desc = descRef.current!.value || '';   // Description (default empty string)

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
            handleError(t('lib.enterLibraryName', { ns: 'bs' }));
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
            handleError(t('lib.nameExists', { ns: 'bs' }));
            return;
        }

        if (descRef.current!.value && desc.length > 200) {
            handleError(t('lib.descriptionLimit', { ns: 'bs' }));
            return;
        }

        if (mode === 'create' && !modelId) {
            handleError(t('lib.selectModel', { ns: 'bs' }));
            return;
        }

        setIsSubmitting(true)
        if (mode === 'create') {
            await createFileLib({
                name,
                description: desc,
                model: modelId,
                type: 0
            }).then(response => {
                const res = response as unknown as { id: string | number };
                (window as Window & { libname?: [string, string] }).libname = [name, desc]
                navigate(isImport
                    ? `/filelib/upload/${res.id}`
                    : `/filelib/${res.id}`
                );
                onOpenChange(false);
            }).catch(showApiError).finally(() => {
                setIsSubmitting(false)
            })
        } else {
            const data = {
                "model_id": modelId,
                "model_type": "embedding",
                "knowledge_id": currentLib!.id,
                "knowledge_name": name,
                "description": desc
            }
            await updateKnowledge(data).then(() => {
                notification.open({ type: "success", description: String(t('updateSuccess') ?? '') })
                onOpenChange(false);
                onLoadEnd()
            }).catch(showApiError).finally(() => {
                setIsSubmitting(false)
            })
        }
    }

    const handleError = (message: string) => {
        notification.open({ type: 'error', description: String(message ?? '') });
    }

    return <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{mode === 'create' ? t('lib.createLibrary', { ns: 'bs' }) : t('knowledgeBaseSettings')}</DialogTitle>
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
                            <div className="text-sm">
                                {(currentLib.create_time || '').replace('T', ' ')}
                            </div>
                        </div>
                    </div>
                )}
                <div className="">
                    <label htmlFor="name" className="bisheng-label">{t('system.libraryName', { ns: 'bs' })}</label>
                    <span className="text-red-500">*</span>
                    <Input name="name" ref={nameRef} defaultValue={mode === 'edit' && currentLib ? currentLib.name : ''} placeholder={t('lib.enterLibraryName', { ns: 'bs' })} className={`col-span-3 ${error.name && 'border-red-400'}`} />
                </div>
                <div className="">
                    <label htmlFor="desc" className="bisheng-label">{t('lib.desc', { ns: 'bs' })}</label>
                    <Textarea id="desc" ref={descRef} defaultValue={mode === 'edit' && currentLib ? currentLib.description : ''} placeholder={t('enterKnowledgeBaseDescription')} rows={8} textareaClassName={`col-span-3 ${error.desc && 'border-red-400'}`} />
                </div>
                <div className="">
                    <label htmlFor="model" className="bisheng-label">{t('lib.embeddingModelSelection', { ns: 'bs' })}</label>
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
                            {t('noAvailableModels')}
                        </div>
                    )}
                    {mode === 'edit' && isModelChanged && (
                        <p className="text-red-500 text-sm mt-1 flex items-center gap-1">
                            <Outlined.Attention className="w-4 h-4" color="#ef4444" />
                            {t('embeddingModelChangeWarning')}
                        </p>
                    )}
                </div>
            </div>
            <DialogFooter>
                <DialogClose>
                    <Button variant="outlined" color="default">{t('cancel')}</Button>
                </DialogClose>
                {mode === 'create' ? (
                    <>
                        <Button variant="outlined" className="flex" onClick={() => handleCreate(false)} disabled={isSubmitting} color="default">
                            {isSubmitting && <Outlined.Loading className="animate-spin mr-1" />}
                            {t('finishCreate')}
                        </Button>
                        <Button type="submit" className="flex" onClick={() => handleCreate(true)} disabled={isSubmitting}>
                            {isSubmitting && <Outlined.Loading className="animate-spin mr-1" />}
                            {t('createImport', { ns: 'bs' })}
                        </Button>
                    </>
                ) : (
                    <Button type="submit" className="flex" onClick={() => handleCreate(false)} disabled={isSubmitting}>
                        {isSubmitting && <Outlined.Loading className="animate-spin mr-1" />}
                        {t('confirm')}
                    </Button>
                )}
            </DialogFooter>
        </DialogContent>
    </Dialog>
}
