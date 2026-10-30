// @ts-strict-ignore
import { Alert, Button, Cascader, Textarea, toast } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import {
    fromModelCascaderValue,
    toModelCascaderOptions,
    toModelCascaderValue,
} from "@/components/bs-comp/formFields/modelOptions";
import { Switch } from "@bisheng/ui";

import { ModelFieldHint } from "../ModelFieldHint";
import { Tooltip as Tip } from "@bisheng/ui";
import { getKnowledgeModelEnvelope, updateKnowledgeModelConfig } from "@/controllers/API/finetune";
import { showApiError } from "@/controllers/request";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { defalutPrompt } from "./WorkbenchModel";
import { FallbackBlockedBanner, InheritedBadge } from "../SystemConfigBanners";
import { useSystemConfigEnvelope } from "../useSystemConfigEnvelope";
import {
    KnowledgeModelIdField,
    normalizeKnowledgeModelIds,
} from "./knowledgeModelValidation";

export const ModelSelect = ({ required = false, close = false, label, tooltipText = '', value, options, onChange, placeholder = '' }) => {
    const { t } = useTranslation()
    const selectLabels = useSelectLabels()
    const cascaderOptions = useMemo(() => toModelCascaderOptions(options), [options])
    const cascaderValue = useMemo(() => toModelCascaderValue(value, options), [options, value])

    return (
        <div className="min-w-0">
            <Label className="bisheng-label inline-flex items-center">
                <span>{label}</span>
                {required && <span className="text-red-500 text-xs">*</span>}
                {tooltipText && <ModelFieldHint className="ml-1" content={tooltipText} />}
            </Label>
            <Cascader
                {...selectLabels}
                className="w-full"
                options={cascaderOptions}
                value={cascaderValue}
                allowClear={close}
                onChange={(path) => onChange(fromModelCascaderValue(path))}
                placeholder={placeholder || t('build.selectModel')}
                aria-label={typeof label === 'string' && label ? label : t('build.selectModel')}
                backLabel={t('sharedUi.back')}
                doneLabel={t('sharedUi.done')}
                searchPlaceholder={t('sharedUi.searchModels')}
            />
        </div>
    );
};


export const PromptDialog = ({ value, onChange, onSave, label, children }) => {
    const { t } = useTranslation('model')
    const [open, setOpen] = useState(false)
    const [saving, setSaving] = useState(false)
    const savingRef = useRef(false)
    const modifyNotSavedRef = useRef(false)
    const [textValue, setTextValue] = useState(value)
    useEffect(() => {
        open && setTextValue(value)
    }, [value, open])

    const handleCancel = () => {
        if (modifyNotSavedRef.current) {
            return bsConfirm({
                title: t('model.cancelEdit'),
                desc: t('model.confirmCancelEdit'),
                onOk: (next) => {
                    next();
                    setOpen(false);
                    // onRestore()
                    modifyNotSavedRef.current = false
                }
            })
        }
        setOpen(false);
    }


    const handleSave = async () => {
        if (savingRef.current) return;
        savingRef.current = true;
        setSaving(true);
        try {
            await onSave(textValue);
            modifyNotSavedRef.current = false;
            onChange(textValue);
            setOpen(false);
        } catch (error) {
            showApiError(error);
        } finally {
            savingRef.current = false;
            setSaving(false);
        }
    };

    return <Dialog open={open} onOpenChange={(next) => { if (!savingRef.current) setOpen(next); }}>
        <DialogTrigger>
            {children}
        </DialogTrigger>
        <DialogContent  className="sm:max-w-[625px] bg-background-login">
            <DialogHeader>
                <DialogTitle>{t('model.editPrompt')}</DialogTitle>
            </DialogHeader>
            <div>
                <Label className="bisheng-label">{label || t('model.docKnowledgeAbstractPrompt')}</Label>
                <Textarea value={textValue} onChange={(e) => {
                        setTextValue(e.target.value)
                        modifyNotSavedRef.current = true;
                    }} rows={16} textareaClassName={"mt-1"} />
            </div>
            <DialogFooter>
                <Button disabled={saving} variant="outlined" type="button" onClick={handleCancel} color="default">{t('model.cancel')}</Button>
                <Button disabled={saving} type="submit" onClick={() => { void handleSave(); }}>
                    {t('model.save')}
                </Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

export function KnowledgeModel({ llmOptions, embeddings, asrModel = [], onBack }) {
    const { t } = useTranslation('model')
    const defaultAutoTagPrompt = t('model.defaultAutoTagPrompt')

    const [form, setForm] = useState({
        embeddingModelId: null,
        sourceModelId: null,
        extractModelId: null,
        qaSimilarModelId: null,
        asrModelId: null,
        abstractEnabled: true,
        autoTagEnabled: true,
        abstractPrompt: '',
        autoTagPrompt: ''
    });
    const lastSaveFormDataRef = useRef(null)
    const [unavailableModelFields, setUnavailableModelFields] = useState<KnowledgeModelIdField[]>([])

    const { config, loading, inheritedFromRoot, fallbackBlocked, clearInherited } =
        useSystemConfigEnvelope<any>(getKnowledgeModelEnvelope)

    useEffect(() => {
        if (!config) return
        const {
            embedding_model_id,
            extract_title_model_id,
            qa_similar_model_id,
            asr_model_id,
            source_model_id,
            abstract_enabled,
            auto_tag_enabled,
            abstract_prompt,
            auto_tag_prompt,
        } = config
        const { modelIds, unavailableFields } = normalizeKnowledgeModelIds(
            {
                embedding_model_id,
                source_model_id,
                extract_title_model_id,
                qa_similar_model_id,
                asr_model_id,
            },
            { llmOptions, embeddings, asrModels: asrModel },
        )
        setForm({
            embeddingModelId: modelIds.embedding_model_id,
            sourceModelId: modelIds.source_model_id,
            extractModelId: modelIds.extract_title_model_id,
            qaSimilarModelId: modelIds.qa_similar_model_id,
            asrModelId: modelIds.asr_model_id,
            abstractEnabled: abstract_enabled ?? true,
            autoTagEnabled: auto_tag_enabled ?? true,
            abstractPrompt: abstract_prompt ?? defalutPrompt,
            autoTagPrompt: auto_tag_prompt ?? defaultAutoTagPrompt,
        })
        lastSaveFormDataRef.current = {
            ...config,
            ...modelIds,
            abstract_prompt: abstract_prompt || defalutPrompt,
            auto_tag_prompt: auto_tag_prompt || defaultAutoTagPrompt,
        }
        setUnavailableModelFields(unavailableFields)
    }, [asrModel, config, defaultAutoTagPrompt, embeddings, llmOptions]);

    // Clear inherited flag on first user edit — the in-memory form no
    // longer reflects Root's value, so the Badge should disappear before
    // the save round-trip flips it on the server side.
    const setFormAndClearInherited = (next: typeof form) => {
        clearInherited()
        setForm(next)
    }

    const handleModelChange = (
        field: KnowledgeModelIdField,
        next: typeof form,
    ) => {
        setUnavailableModelFields((current) => current.filter((item) => item !== field))
        setFormAndClearInherited(next)
    }


    const [saveload, setSaveLoad] = useState(false)
    const handleSave = async () => {
        const {
            embeddingModelId,
            extractModelId,
            qaSimilarModelId,
            asrModelId,
            sourceModelId,
            abstractEnabled,
            autoTagEnabled,
            abstractPrompt,
            autoTagPrompt,
        } = form
        const errors = []
        if (!embeddingModelId) {
            errors.push(t('model.defaultEmbeddingModel') + t('bs:required'))
        }
        if ((abstractEnabled || autoTagEnabled) && !extractModelId) {
            errors.push(t('model.documentSummaryModel') + t('bs:required'))
        }
        if (!qaSimilarModelId) {
            errors.push(t('model.qaSimilarModel') + t('bs:required'))
        }
        if (errors.length) return toast.show({ type: 'error', message: errors.filter(Boolean).join('\n') })

        const data = {
            embedding_model_id: embeddingModelId,
            extract_title_model_id: extractModelId,
            qa_similar_model_id: qaSimilarModelId,
            asr_model_id: asrModelId || null,
            source_model_id: sourceModelId,
            abstract_enabled: abstractEnabled,
            auto_tag_enabled: autoTagEnabled,
            abstract_prompt: abstractPrompt,
            auto_tag_prompt: autoTagPrompt
        }
        setSaveLoad(true)
        try {
            await updateKnowledgeModelConfig(data);
            lastSaveFormDataRef.current = data;
            setUnavailableModelFields([]);
            toast.show({ type: 'success', message: String(t('model.saveSuccess') ?? '') });
        } catch (error) {
            showApiError(error);
        } finally {
            setSaveLoad(false);
        }
    };

    // Persist a single prompt edit (abstract or auto-tag) without going
    // through the main save flow, mirroring the existing per-prompt save
    // semantics. Caller passes the patch keyed by the backend field name.
    const handleSavePrompt = (patch: { abstract_prompt?: string; auto_tag_prompt?: string }) => {
        return updateKnowledgeModelConfig({
            ...lastSaveFormDataRef.current,
            ...patch,
        }).then(res => {
            lastSaveFormDataRef.current = { ...lastSaveFormDataRef.current, ...patch }
            toast.show({ type: 'success', message: String(t('model.promptSaved') ?? '') })
        })
    }

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <Outlined.Loading  className="size-4 animate-spin"/>
    </div>

    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16 relative">
            <FallbackBlockedBanner visible={fallbackBlocked} />
            {unavailableModelFields.length > 0 && (
                <Alert
                    type="warning"
                    description={t('model.unavailableSelectionsCleared')}
                    live
                />
            )}
            {inheritedFromRoot && (
                <div className="-mb-2 text-xs text-muted-foreground flex items-center">
                    <InheritedBadge visible={true} />
                </div>
            )}
            <ModelSelect
                required
                label={t('model.defaultEmbeddingModel')}
                value={form.embeddingModelId}
                options={embeddings}
                onChange={(val) => handleModelChange('embedding_model_id', { ...form, embeddingModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.sourceTracingModel')}
                tooltipText={t('model.sourceTracingModelTooltip')}
                value={form.sourceModelId}
                options={llmOptions}
                onChange={(val) => handleModelChange('source_model_id', { ...form, sourceModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.documentSummaryModel')}
                tooltipText={t('model.documentSummaryModelTooltip')}
                value={form.extractModelId}
                options={llmOptions}
                onChange={(val) => handleModelChange('extract_title_model_id', { ...form, extractModelId: val })}
            />
            <div className="rounded-md border p-4 space-y-4">
                <div className="flex items-center justify-between gap-6">
                    <Label className="bisheng-label mb-0">{t('model.summaryGeneration')}</Label>
                    <div className="flex items-center gap-2">
                        <PromptDialog
                            value={form.abstractPrompt}
                            label={t('model.docKnowledgeAbstractPrompt')}
                            onChange={value => setFormAndClearInherited({ ...form, abstractPrompt: value })}
                            onSave={(prompt) => handleSavePrompt({ abstract_prompt: prompt ?? form.abstractPrompt })}
                            onRestore={() => setFormAndClearInherited({ ...form, abstractPrompt: lastSaveFormDataRef.current.abstract_prompt })}
                        >
                            <Tip content={t('model.docKnowledgeAbstractPromptTooltip')} side="top">
                                <Button variant="link" size="small" className="h-auto px-0">
                                    <Outlined.Setting size={14} className="mr-1" />
                                    {t('model.editPromptButton')}
                                </Button>
                            </Tip>
                        </PromptDialog>
                        <Switch
                            checked={form.abstractEnabled}
                            onCheckedChange={(val) => setFormAndClearInherited({ ...form, abstractEnabled: val })}
                        />
                    </div>
                </div>
                <div className="flex items-center justify-between gap-6">
                    <Label className="bisheng-label mb-0">{t('model.autoTagGeneration')}</Label>
                    <div className="flex items-center gap-2">
                        <PromptDialog
                            value={form.autoTagPrompt}
                            label={t('model.autoTagPrompt')}
                            onChange={value => setFormAndClearInherited({ ...form, autoTagPrompt: value })}
                            onSave={(prompt) => handleSavePrompt({ auto_tag_prompt: prompt ?? form.autoTagPrompt })}
                            onRestore={() => setFormAndClearInherited({ ...form, autoTagPrompt: lastSaveFormDataRef.current.auto_tag_prompt })}
                        >
                            <Tip content={t('model.autoTagPromptTooltip')} side="top">
                                <Button variant="link" size="small" className="h-auto px-0">
                                    <Outlined.Setting size={14} className="mr-1" />
                                    {t('model.editPromptButton')}
                                </Button>
                            </Tip>
                        </PromptDialog>
                        <Switch
                            checked={form.autoTagEnabled}
                            onCheckedChange={(val) => setFormAndClearInherited({ ...form, autoTagEnabled: val })}
                        />
                    </div>
                </div>
            </div>
            <ModelSelect
                required
                label={t('model.qaSimilarModel')}
                tooltipText={t('model.qaSimilarModelTooltip')}
                value={form.qaSimilarModelId}
                options={llmOptions}
                onChange={(val) => handleModelChange('qa_similar_model_id', { ...form, qaSimilarModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.asrModel')}
                tooltipText={t('model.knowledgeAsrModelTooltip')}
                value={form.asrModelId}
                options={asrModel}
                onChange={(val) => handleModelChange('asr_model_id', { ...form, asrModelId: val })}
            />
            <div className="mt-10 text-center space-x-6">
                <Button variant="outlined" onClick={onBack} color="default">{t('model.cancel')}</Button>
                <Button disabled={saveload || !config} onClick={handleSave}>
                    {saveload && <Outlined.Loading className="animate-spin mr-2" />}
                    {t('model.save')}
                </Button>
            </div>
        </div>
    );
}
