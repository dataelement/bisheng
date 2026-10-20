import { isNumberDraftWithinBounds } from '@/utils/fieldValidation';
import { Button, Input, Textarea } from '@bisheng/ui';
import { Switch, Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { ModelFieldHint } from "./ModelFieldHint";
import { getAdvancedParamsTemplate, templateToJsonString } from "@/util/advancedParamsTemplates";
import { useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";

export interface ModelItemConfig {
    enable_web_search?: boolean;
    max_tokens?: number;
    // Saved by this UI as a JSON string; models created through the API or
    // older versions may store a plain object instead. The backend accepts both.
    user_kwargs?: string | Record<string, unknown>;
    voice?: string;
    [key: string]: unknown;
}

export interface ModelItemData {
    id: string | number;
    name: string;
    model_name: string;
    model_type: string;
    voice?: string;
    config?: ModelItemConfig | null;
}

interface ModelItemProps {
    data: ModelItemData;
    /** Provider value of the parent server, e.g. `qwen`. */
    type: string;
    onDelete: () => void;
    /** Returns a truthy value when the name duplicates a sibling model. */
    onInput: (name: string, modelType: string) => unknown;
    onConfig: (config: ModelItemConfig) => void;
}

// Providers whose backend params handler consumes `enable_web_search`
// (see bisheng/llm/domain/llm/llm.py). Each provider runs the search in a
// different way, so each one gets its own tooltip copy.
const WEB_SEARCH_TIP_KEYS: Record<string, string> = {
    qwen: 'model.webSearchTipQwen',
    moonshot: 'model.webSearchTipMoonshot',
    tencent: 'model.webSearchTipTencent',
};

const MODEL_TYPE_LABELS: Record<string, string> = {
    llm: 'LLM',
    embedding: 'Embedding',
    rerank: 'Rerank',
    asr: 'ASR',
    tts: 'TTS',
};

const ASR_TTS_PROVIDERS = ['azure_openai', 'openai', 'qwen', 'qianfan'];

// The UI field is always stored as `max_tokens`; the backend renames it per
// provider, and for ollama it becomes the context window, not an output cap.
function maxTokensParamName(provider: string): string {
    if (provider === 'qianfan') return 'max_output_tokens';
    if (provider === 'ollama') return 'num_ctx';
    return 'max_tokens';
}

// Normalize `user_kwargs` to the JSON text shown in the editor.
function userKwargsToText(value: unknown): string {
    if (value === undefined || value === null) return '';
    if (typeof value === 'string') return value.trim();
    return JSON.stringify(value, null, 2);
}

function parseParamsObject(text: string): Record<string, unknown> | null {
    try {
        const parsed: unknown = JSON.parse(text);
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
        return parsed as Record<string, unknown>;
    } catch {
        return null;
    }
}

export function ModelItem({ data, type, onDelete, onInput, onConfig }: ModelItemProps) {
    const { t } = useTranslation();
    const [nameError, setNameError] = useState('');
    const [dialogOpen, setDialogOpen] = useState(false);
    const [draftParams, setDraftParams] = useState('');
    const [jsonError, setJsonError] = useState(false);

    const config: ModelItemConfig = data.config ?? {};
    const modelType = data.model_type;
    const hasAdvancedParams = modelType === 'llm' || modelType === 'embedding';
    const webSearchTipKey = modelType === 'llm' ? WEB_SEARCH_TIP_KEYS[type] : undefined;
    const paramName = maxTokensParamName(type);

    const savedParams = userKwargsToText(config.user_kwargs);
    const savedParamCount = savedParams ? Object.keys(parseParamsObject(savedParams) ?? {}).length : 0;
    const paramsTemplate = hasAdvancedParams
        ? templateToJsonString(getAdvancedParamsTemplate(type, modelType as 'llm' | 'embedding'))
        : '';

    // Merge a partial change into the model config; `undefined` drops the key.
    const applyConfig = (patch: Partial<ModelItemConfig>) => {
        const next: ModelItemConfig = { ...config, ...patch };
        Object.keys(patch).forEach(key => {
            if (next[key] === undefined) delete next[key];
        });
        onConfig(next);
    };

    const handleNameChange = (e: ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value;
        const repeated = onInput(value, modelType);
        if (!value) setNameError(t('model.modelNameEmpty'));
        else if (value.length > 100) setNameError(t('model.modelNameLength'));
        else if (repeated) setNameError(t('model.modelNameDuplicate'));
        else setNameError('');
    };

    const handleMaxTokensChange = (e: ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value;
        applyConfig({ max_tokens: value === '' ? undefined : parseInt(value, 10) });
    };

    const handleDeleteClick = () => {
        bsConfirm({
            desc: t('model.deleteModelConfirmation'),
            onOk(next: () => void) {
                onDelete();
                next();
            }
        });
    };

    // Opening the dialog must not touch the config: the draft is local until
    // the user clicks save. The provider template is only a placeholder.
    const handleOpenParams = () => {
        setDraftParams(savedParams);
        setJsonError(false);
        setDialogOpen(true);
    };

    const handleDraftChange = (value: string) => {
        setDraftParams(value);
        setJsonError(value.trim() !== '' && parseParamsObject(value.trim()) === null);
    };

    const handleSaveParams = () => {
        if ((String(config.max_tokens ?? '') !== '' && (!Number.isFinite(Number(config.max_tokens ?? '')) || Number(config.max_tokens ?? '') < 0))) return;

        const value = draftParams.trim();
        if (value && parseParamsObject(value) === null) {
            setJsonError(true);
            return;
        }
        applyConfig({ user_kwargs: value });
        setDialogOpen(false);
    };

    const displayName = data.model_name.trim() || t('model.untitledModel');

    return (
        <div className="rounded-md border p-4">
            <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                    <span className={`truncate text-sm font-medium ${data.model_name.trim() ? '' : 'text-muted-foreground'}`}>
                        {displayName}
                    </span>
                    <Tag size="small" className="shrink-0">{MODEL_TYPE_LABELS[modelType] ?? modelType}</Tag>
                </div>
                <Button variant="text" size="medium" className="size-8 shrink-0 text-muted-foreground" aria-label={t('model.deleteModel')} onClick={handleDeleteClick} color="default" iconOnly>
                    <Outlined.Delete />
                </Button>
            </div>

            <div className="mt-3 grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
                <div className="space-y-2">
                    <Label className="bisheng-label flex h-8 items-center">
                        <span>{t('model.modelName')}</span>
                        <ModelFieldHint className="ml-1" content={t('model.modelNameTooltip')} />
                    </Label>
                    <Input aria-label={t('model.modelName')} value={data.model_name} onChange={handleNameChange} className={"h-8"} />
                    {nameError && <span className="text-xs text-red-500">{nameError}</span>}
                </div>
                <div className="space-y-2">
                    <Label className="bisheng-label flex h-8 items-center">{t('model.modelType')}</Label>
                    <Select value={modelType} onValueChange={(val: string) => onInput(data.model_name, val)}>
                        <SelectTrigger className="h-8">
                            <SelectValue placeholder="" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="llm">LLM</SelectItem>
                                <SelectItem value="embedding">Embedding</SelectItem>
                                <SelectItem value="rerank">Rerank</SelectItem>
                                {ASR_TTS_PROVIDERS.includes(type) && (
                                    <>
                                        <SelectItem value="asr">ASR</SelectItem>
                                        <SelectItem value="tts">TTS</SelectItem>
                                    </>
                                )}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
            </div>

            {modelType === 'tts' && (
                <div className="mt-4 space-y-2">
                    <Label className="bisheng-label">
                        <span>{t('model.voiceType')}</span>
                        <span className="text-red-500">*</span>
                        <ModelFieldHint className="ml-1" content={t('model.voiceTypeTooltip')} />
                    </Label>
                    <Input aria-label={t('model.voiceType')} value={config.voice ?? data.voice ?? ''} onChange={(e) => applyConfig({ voice: e.target.value })} className={"h-8"} />
                </div>
            )}

            {modelType === 'llm' && (
                <div className="mt-4 space-y-2">
                    <Label className="bisheng-label">
                        <span>{paramName === 'num_ctx' ? t('model.contextLength') : t('model.maxOutputTokens')}</span>
                        <ModelFieldHint
                            className="ml-1"
                            content={t('model.maxTokensTip', { param: paramName })}
                        />
                    </Label>
                    <Input type="number" aria-label={paramName} value={config.max_tokens ?? ''} onChange={(event) => { if (!isNumberDraftWithinBounds(event.currentTarget.value, {  })) return; handleMaxTokensChange(event); }} placeholder={t('model.maxTokensPlaceholder')} className={"h-8"} />
                </div>
            )}

            {webSearchTipKey && (
                <div className="mt-4 flex items-center justify-between gap-4 border-t pt-4">
                    <Label className="bisheng-label">
                        <span>{t('model.webSearch')}</span>
                        <ModelFieldHint className="ml-1" content={t(webSearchTipKey)} />
                    </Label>
                    <Switch
                        aria-label={t('model.webSearch')}
                        checked={!!config.enable_web_search}
                        onCheckedChange={(checked: boolean) => applyConfig({ enable_web_search: checked })}
                    />
                </div>
            )}

            {hasAdvancedParams && (
                <div className="mt-4 flex items-center justify-between gap-4 border-t pt-4">
                    <div className="flex min-w-0 items-center gap-2">
                        <Label className="bisheng-label">{t('model.advancedParams')}</Label>
                        <span className="truncate text-xs text-muted-foreground">
                            {savedParamCount > 0
                                ? t('model.advancedParamsCount', { count: savedParamCount })
                                : t('model.advancedParamsNone')}
                        </span>
                    </div>
                    <Button variant="link" size="small" className="h-auto shrink-0 px-0" onClick={handleOpenParams}>
                        {t('model.edit')}
                    </Button>
                </div>
            )}

            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogContent className="sm:max-w-[625px]">
                    <DialogHeader>
                        <DialogTitle>{t('model.advancedParamsConfig')}</DialogTitle>
                    </DialogHeader>
                    <div className="mt-4 text-gray-500">
                        <div className="flex items-center justify-between gap-4">
                            <Label>{t('model.pasteAdvancedParamsHere')}</Label>
                            <Button variant="link" size="small" className="h-auto shrink-0 px-0" onClick={() => handleDraftChange(paramsTemplate)}>
                                {t('model.insertParamsExample')}
                            </Button>
                        </div>
                        <Textarea aria-label={t('model.pasteAdvancedParamsHere')} value={draftParams} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => handleDraftChange(e.target.value)} rows={10} placeholder={paramsTemplate} textareaClassName={`mt-1 font-mono text-sm ${jsonError ? 'border-red-500 focus-visible:ring-red-500' : ''}`} />
                        {jsonError && (
                            <span className="mt-1 inline-block text-xs text-red-500">
                                {t('model.errorInvalidJsonFormat')}
                            </span>
                        )}
                    </div>
                    <DialogFooter className="mt-4">
                        <Button variant="outlined" onClick={() => setDialogOpen(false)} color="default">{t('model.cancel')}</Button>
                        <Button onClick={handleSaveParams} disabled={(String(config.max_tokens ?? '') !== '' && (!Number.isFinite(Number(config.max_tokens ?? '')) || Number(config.max_tokens ?? '') < 0))}>{t('model.save')}</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
