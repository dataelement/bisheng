import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import Tip from "@/components/bs-ui/tooltip/tip";
import { getKnowledgeModelEnvelope, updateKnowledgeModelConfig } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Settings } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { defalutPrompt } from "./WorkbenchModel";
import { FallbackBlockedBanner, InheritedBadge } from "../SystemConfigBanners";
import { useSystemConfigEnvelope } from "../useSystemConfigEnvelope";

export const ModelSelect = ({ required = false, close = false, label, tooltipText = '', value, options, onChange, footer = null }) => {

    const defaultValue = useMemo(() => {
        let _defaultValue = []
        if (!value) return _defaultValue
        options.some(option => {
            const model = option.children.find(el => el.value === value)
            if (model) {
                _defaultValue = [{ value: option.value, label: option.label }, { value: model.value, label: model.label }]
                return true
            }
        })
        return _defaultValue
    }, [value, options])

    return (
        <div>
            <Label className="bisheng-label">
                <span>{label}</span>
                {required && <span className="text-red-500 text-xs">*</span>}
                {tooltipText && <QuestionTooltip className="relative top-0.5 ml-1" content={tooltipText} />}
            </Label>
            <Cascader
                defaultValue={defaultValue}
                options={options}
                close={close}
                onChange={(val) => onChange(val[1])}
                footer={footer}
            />
        </div>
    );
};


// Default system prompt for knowledge-space auto tagging. Mirrors the
// server-side `DEFAULT_AUTO_TAG_SYSTEM_PROMPT` so the textarea opens
// with a sensible starting value when the tenant has not customised it.
export const defaultAutoTagPrompt = `你是文件自动标签分类器。只能从候选标签中选择最相关的标签，最多返回 5 个标签。
输出格要求严格遵循 JSON 格式： {"tags": ["标签名"]}。`;

const PromptDialog = ({ value, onChange, onRestore, onSave, label, children }) => {
    const { t } = useTranslation('model')
    const [open, setOpen] = useState(false)
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


    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger>
            {children}
        </DialogTrigger>
        <DialogContent  className="sm:max-w-[625px] bg-background-login">
            <DialogHeader>
                <DialogTitle>{t('model.editPrompt')}</DialogTitle>
            </DialogHeader>
            <div>
                <Label className="bisheng-label">{label || t('model.docKnowledgeAbstractPrompt')}</Label>
                <Textarea
                    value={textValue}
                    onChange={(e) => {
                        setTextValue(e.target.value)
                        modifyNotSavedRef.current = true;
                    }}
                    className="mt-1"
                    rows={16}
                />
            </div>
            <DialogFooter>
                <Button variant="outline" className="px-11" type="button" onClick={handleCancel}>{t('model.cancel')}</Button>
                <Button disabled={false} type="submit" className="px-11" onClick={() => {
                    modifyNotSavedRef.current = false
                    onSave(textValue)
                    setOpen(false)
                    onChange(textValue)
                }}>
                    {t('model.save')}
                </Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}

export default function KnowledgeModel({ llmOptions, embeddings, onBack }) {
    const { t } = useTranslation('model')

    const [form, setForm] = useState({
        embeddingModelId: null,
        sourceModelId: null,
        extractModelId: null,
        qaSimilarModelId: null,
        abstractEnabled: true,
        autoTagEnabled: true,
        abstractPrompt: '',
        autoTagPrompt: ''
    });
    // 最后保存的配置
    const lastSaveFormDataRef = useRef(null)

    const { config, loading, inheritedFromRoot, fallbackBlocked, clearInherited } =
        useSystemConfigEnvelope<any>(getKnowledgeModelEnvelope)

    useEffect(() => {
        if (!config) return
        const {
            embedding_model_id,
            extract_title_model_id,
            qa_similar_model_id,
            source_model_id,
            abstract_enabled,
            auto_tag_enabled,
            abstract_prompt,
            auto_tag_prompt,
        } = config
        setForm({
            embeddingModelId: embedding_model_id,
            sourceModelId: source_model_id,
            extractModelId: extract_title_model_id,
            qaSimilarModelId: qa_similar_model_id,
            abstractEnabled: abstract_enabled ?? true,
            autoTagEnabled: auto_tag_enabled ?? true,
            abstractPrompt: abstract_prompt ?? defalutPrompt,
            autoTagPrompt: auto_tag_prompt ?? defaultAutoTagPrompt,
        })
        lastSaveFormDataRef.current = {
            ...config,
            abstract_prompt: abstract_prompt || defalutPrompt,
            auto_tag_prompt: auto_tag_prompt || defaultAutoTagPrompt,
        }
    }, [config]);

    // Clear inherited flag on first user edit — the in-memory form no
    // longer reflects Root's value, so the Badge should disappear before
    // the save round-trip flips it on the server side.
    const setFormAndClearInherited = (next: typeof form) => {
        clearInherited()
        setForm(next)
    }

    const { message } = useToast()
    const [saveload, setSaveLoad] = useState(false)
    const handleSave = async () => {
        const {
            embeddingModelId,
            extractModelId,
            qaSimilarModelId,
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
        if (errors.length) return message({ variant: 'error', description: errors })

        const data = {
            embedding_model_id: embeddingModelId,
            extract_title_model_id: extractModelId,
            qa_similar_model_id: qaSimilarModelId,
            source_model_id: sourceModelId,
            abstract_enabled: abstractEnabled,
            auto_tag_enabled: autoTagEnabled,
            abstract_prompt: abstractPrompt,
            auto_tag_prompt: autoTagPrompt
        }
        setSaveLoad(true)
        await captureAndAlertRequestErrorHoc(updateKnowledgeModelConfig(data).then(res => {
            lastSaveFormDataRef.current = data
            message({ variant: 'success', description: t('model.saveSuccess') })
        }))
        setSaveLoad(false)
    };

    // Persist a single prompt edit (abstract or auto-tag) without going
    // through the main save flow, mirroring the existing per-prompt save
    // semantics. Caller passes the patch keyed by the backend field name.
    const handleSavePrompt = (patch: { abstract_prompt?: string; auto_tag_prompt?: string }) => {
        captureAndAlertRequestErrorHoc(updateKnowledgeModelConfig({
            ...lastSaveFormDataRef.current,
            ...patch,
        }).then(res => {
            lastSaveFormDataRef.current = { ...lastSaveFormDataRef.current, ...patch }
            message({ variant: 'success', description: t('model.promptSaved') })
        }))
    }

    if (loading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return (
        <div className="max-w-[520px] mx-auto gap-y-4 flex flex-col mt-16 relative">
            <FallbackBlockedBanner visible={fallbackBlocked} />
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
                onChange={(val) => setFormAndClearInherited({ ...form, embeddingModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.sourceTracingModel')}
                tooltipText={t('model.sourceTracingModelTooltip')}
                value={form.sourceModelId}
                options={llmOptions}
                onChange={(val) => setFormAndClearInherited({ ...form, sourceModelId: val })}
            />
            <ModelSelect
                close
                label={t('model.documentSummaryModel')}
                tooltipText={t('model.documentSummaryModelTooltip')}
                value={form.extractModelId}
                options={llmOptions}
                onChange={(val) => setFormAndClearInherited({ ...form, extractModelId: val })}
            />
            <div className="rounded-md border p-4 space-y-4">
                <div className="flex items-center justify-between gap-6">
                    <Label className="bisheng-label mb-0">{t('model.summaryGeneration', '摘要生成')}</Label>
                    <div className="flex items-center gap-2">
                        <PromptDialog
                            value={form.abstractPrompt}
                            label={t('model.docKnowledgeAbstractPrompt')}
                            onChange={value => setFormAndClearInherited({ ...form, abstractPrompt: value })}
                            onSave={(prompt) => handleSavePrompt({ abstract_prompt: prompt ?? form.abstractPrompt })}
                            onRestore={() => setFormAndClearInherited({ ...form, abstractPrompt: lastSaveFormDataRef.current.abstract_prompt })}
                        >
                            <Tip content={t('model.docKnowledgeAbstractPromptTooltip')} side="top">
                                <Button variant="link" size="sm" className="h-auto px-0">
                                    <Settings size={14} className="mr-1" />
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
                    <Label className="bisheng-label mb-0">{t('model.autoTagGeneration', '自动标签生成')}</Label>
                    <div className="flex items-center gap-2">
                        <PromptDialog
                            value={form.autoTagPrompt}
                            label={t('model.autoTagPrompt', '自动标签提示词')}
                            onChange={value => setFormAndClearInherited({ ...form, autoTagPrompt: value })}
                            onSave={(prompt) => handleSavePrompt({ auto_tag_prompt: prompt ?? form.autoTagPrompt })}
                            onRestore={() => setFormAndClearInherited({ ...form, autoTagPrompt: lastSaveFormDataRef.current.auto_tag_prompt })}
                        >
                            <Tip content={t('model.autoTagPromptTooltip', '编辑用于自动标签分类的系统提示词')} side="top">
                                <Button variant="link" size="sm" className="h-auto px-0">
                                    <Settings size={14} className="mr-1" />
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
                onChange={(val) => setFormAndClearInherited({ ...form, qaSimilarModelId: val })}
            />
            <div className="mt-10 text-center space-x-6">
                <Button className="px-6" variant="outline" onClick={onBack}>{t('model.cancel')}</Button>
                <Button
                    className="px-10"
                    disabled={saveload}
                    onClick={handleSave}
                >
                    {saveload && <LoadIcon className="mr-2" />}
                    {t('model.save')}
                </Button>
            </div>
        </div>
    );
}
