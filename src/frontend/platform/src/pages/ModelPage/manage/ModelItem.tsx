import { Badge } from "@/components/bs-ui/badge";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { getAdvancedParamsTemplate, templateToJsonString } from "@/util/advancedParamsTemplates";
import { Trash2Icon } from "lucide-react";
import { useState, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";

export interface ModelItemConfig {
    enable_web_search?: boolean;
    max_tokens?: number;
    user_kwargs?: string;
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

    const savedParams = (config.user_kwargs ?? '').trim();
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
                    <Badge variant="gray" className="shrink-0">{MODEL_TYPE_LABELS[modelType] ?? modelType}</Badge>
                </div>
                <Button
                    variant="ghost"
                    size="icon"
                    className="size-8 shrink-0 text-muted-foreground"
                    aria-label={t('model.deleteModel')}
                    onClick={handleDeleteClick}
                >
                    <Trash2Icon className="size-4" />
                </Button>
            </div>

            <div className="mt-3 grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(200px,1fr))]">
                <div className="space-y-2">
                    <Label className="bisheng-label">
                        <span>{t('model.modelName')}</span>
                        <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.modelNameTooltip')} />
                    </Label>
                    <Input value={data.model_name} onChange={handleNameChange} className="h-8" />
                    {nameError && <span className="text-xs text-red-500">{nameError}</span>}
                </div>
                <div className="space-y-2">
                    <Label className="bisheng-label">{t('model.modelType')}</Label>
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
                        <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.voiceTypeTooltip')} />
                    </Label>
                    <Input
                        value={config.voice ?? data.voice ?? ''}
                        onChange={(e) => applyConfig({ voice: e.target.value })}
                        className="h-8"
                    />
                </div>
            )}

            {modelType === 'llm' && (
                <div className="mt-4 space-y-2">
                    <Label className="bisheng-label">
                        <span>{paramName === 'num_ctx' ? t('model.contextLength') : t('model.maxOutputTokens')}</span>
                        <QuestionTooltip
                            className="relative top-0.5 ml-1"
                            content={t('model.maxTokensTip', { param: paramName })}
                        />
                    </Label>
                    <Input
                        type="number"
                        value={config.max_tokens ?? ''}
                        onChange={handleMaxTokensChange}
                        placeholder={t('model.maxTokensPlaceholder')}
                        className="h-8"
                    />
                </div>
            )}

            {webSearchTipKey && (
                <div className="mt-4 flex items-center justify-between gap-4 border-t pt-4">
                    <Label className="bisheng-label">
                        <span>{t('model.webSearch')}</span>
                        <QuestionTooltip className="relative top-0.5 ml-1" content={t(webSearchTipKey)} />
                    </Label>
                    <Switch
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
                    <Button variant="link" size="sm" className="h-auto shrink-0 px-0" onClick={handleOpenParams}>
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
                            <Button
                                variant="link"
                                size="sm"
                                className="h-auto shrink-0 px-0"
                                onClick={() => handleDraftChange(paramsTemplate)}
                            >
                                {t('model.insertParamsExample')}
                            </Button>
                        </div>
                        <Textarea
                            value={draftParams}
                            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => handleDraftChange(e.target.value)}
                            className={`mt-1 font-mono text-sm ${jsonError ? 'border-red-500 focus-visible:ring-red-500' : ''}`}
                            rows={10}
                            placeholder={paramsTemplate}
                        />
                        {jsonError && (
                            <span className="mt-1 inline-block text-xs text-red-500">
                                {t('model.errorInvalidJsonFormat')}
                            </span>
                        )}
                    </div>
                    <DialogFooter className="mt-4">
                        <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('model.cancel')}</Button>
                        <Button onClick={handleSaveParams}>{t('model.save')}</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
