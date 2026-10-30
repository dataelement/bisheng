// @ts-strict-ignore
import { isNumberDraftWithinBounds } from '@/utils/fieldValidation';
import { Alert, Button, Input, Select, toast } from '@bisheng/ui';

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";


import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { Button as SharedButton, Switch, Tooltip as SharedTooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { ModelFieldHint } from "./ModelFieldHint";
import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { addLLmServer, deleteLLmServer, getLLmServerDetail, updateLLmServer } from "@/controllers/API/finetune";
import { showApiError } from "@/controllers/request";
import { useAdminScope } from "@/hooks/useAdminScope";
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CustomForm } from "./CustomForm";
import { canShareToChildren, isGlobalSuperUser } from "./permissions";
import { useLinsightConfig } from "./tabs/WorkbenchModel";
import { useModelProviderInfo } from "./useLink";
import { ModelItem } from "./ModelItem";
import { hasDuplicateModelName, hasInvalidModelName, trimModelNames } from "./modelNameTrim";

// `group` is an i18n key under model.providerGroups; ungrouped entries stay on top, groups follow in first-appearance order.
export const modelProvider = [
    { "name": "", "labelKey": "model.providerNames.openaiCompatible", "value": "openai_compatible" },
    { "name": "OpenAI", "value": "openai", "group": "cloud" },
    { "name": "Azure OpenAI", "value": "azure_openai", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.qwen", "value": "qwen", "group": "cloud" },
    { "name": "DeepSeek", "value": "deepseek", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.silicon", "value": "silicon", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.volcengine", "value": "volcengine", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.zhipu", "value": "zhipu", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.spark", "value": "spark", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.tencent", "value": "tencent", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.moonshot", "value": "moonshot", "group": "cloud" },
    { "name": "", "labelKey": "model.providerNames.qianfan", "value": "qianfan", "group": "cloud" },
    { "name": "Minimax", "value": "minimax", "group": "cloud" },
    { "name": "Anthropic", "value": "anthropic", "group": "cloud" },
    { "name": "Ollama", "value": "ollama", "group": "local" },
    { "name": "xinference", "value": "xinference", "group": "local" },
    { "name": "llamacpp", "value": "llamacpp", "group": "local" },
    { "name": "vllm", "value": "vllm", "group": "local" },
    { "name": "MindIE", "value": "MindIE", "group": "local" },
]
const bishengModelProvider = { "name": "bishengRT", "value": "bisheng_rt", "group": "local" }

// Admins looking for a "custom" provider search for these words; they all lead to the OpenAI-compatible type.
const OPENAI_COMPATIBLE_SEARCH_WORDS = ['custom', 'compatible', 'one api', 'oneapi', 'gateway', 'proxy']

// Providers with a localized display name carry `labelKey`; the rest use `name` as-is.
const providerLabel = (provider, translate) => provider?.labelKey ? translate(provider.labelKey) : (provider?.name || '')

const defaultForm = {
    id: null as any,
    type: '',
    name: '',
    limit_flag: false,
    limit: 1,
    config: {},
    models: [],
    // Root-only switch; default true to match backend LLMServerCreateReq
    // default and v2.5.1 decision-2 ("default share, opt-out via UI").
    share_to_children: true,
    // Echoed by the backend so we can hide the toggle on Root servers
    // viewed under a Child scope (those rows are read-only anyway).
    is_root_shared_readonly: false,
    tenant_id: undefined,
}

export default function ModelConfig({ id, onGetName, onBack, onReload, onBerforSave, onAfterSave }) {
    const { t } = useTranslation()
    const selectLabels = useSelectLabels()
    const { refetch: refetchConfig } = useLinsightConfig();
    const { user } = useContext(userContext);
    const { appConfig } = useContext(locationContext);

    const [formData, setFormData] = useState({ ...defaultForm })
    const [nameError, setNameError] = useState('')
    const [detailError, setDetailError] = useState<unknown>(null)
    const [detailLoading, setDetailLoading] = useState(id !== -1)
    const [detailReload, setDetailReload] = useState(0)

    // Create mode reads the admin scope fresh instead of taking it from the
    // list page: the scope is a server-side lease that can expire while the
    // user sits on the list, and only the value at open time matches the
    // tenant the backend will write on save.
    const isCreate = id === -1;
    const { scope: adminScope } = useAdminScope({
        enabled: appConfig.multiTenantEnabled && isGlobalSuperUser(user) && isCreate,
    });
    const showShareToggle = canShareToChildren({
        multiTenantEnabled: appConfig.multiTenantEnabled,
        user,
        isCreate,
        serverTenantId: formData.tenant_id,
        scopeTenantId: adminScope.scope_tenant_id,
    });

    useEffect(() => {
        let active = true;
        setDetailError(null);
        setFormData({ ...defaultForm });
        setDetailLoading(id !== -1);
        if (id === -1) return;
        void getLLmServerDetail(id).then(res => {
            if (active) setFormData(res);
        }).catch(error => {
            if (!active) return;
            setDetailError(error);
            showApiError(error);
        }).finally(() => { if (active) setDetailLoading(false); });
        return () => { active = false; };
    }, [id, detailReload])

    const getModelsByType = useSelectModel()
    const handleTypeChange = (val) => {
        const name = onGetName(providerLabel(_modelProvider.find(el => el.value === val), t))
        const models = getModelsByType(val)
        setFormData({ ...formData, type: val, name, models, config: {} })
    }

    const handleAddModel = () => {
        if (formData.limit_flag && (String((formData.limit) ?? '') !== '' && (!Number.isFinite(Number(formData.limit)) || Number(formData.limit) < 1))) return;

        const maxIndex = formData.models.reduce((max, el, i) => el.name.match(/model (\d+)/) ? Math.max(max, +el.name.match(/model (\d+)/)[1]) : max, 0)

        const model = {
            id: generateUUID(4),
            name: `model ${maxIndex + 1}`,
            model_name: '',
            model_type: 'llm',
            voice: ''
        }
        setFormData({ ...formData, models: [...formData.models, model] })
    }

    const handleDelete = (index) => {
        const models = formData.models.filter((el, i) => index !== i)
        setFormData({ ...formData, models })
    }

    const handleModelChange = (name, type, index) => {
        const models = formData.models.map((el, i) => index === i ? {
            ...el,
            // Type-specific settings do not carry over to another model type
            config: type === el.model_type ? el.config : null,
            model_name: name,
            model_type: type,
            voice: type === 'tts' ? (el.voice || '') : ''
        } : el)
        setFormData({ ...formData, models })
        return formData.models.find((el, i) => index !== i && el.model_name === name)
    }

    const handleModelConfig = (config, index) => {
        const models = formData.models.map((el, i) => index === i ? {
            ...el,
            config
        } : el)
        setFormData({ ...formData, models })
    }


    const formRef = useRef(null)
    const [isLoading, setIsLoading] = useState(false);
    const handleSave = async () => {
        if (formData.limit_flag && (String((formData.limit) ?? '') !== '' && (!Number.isFinite(Number(formData.limit)) || Number(formData.limit) < 1))) return;

        setIsLoading(true)
        try {
            const exists = onBerforSave(formData.id, formData.name)
            if (exists) {
                return toast.show({ type: 'warning', message: String(t('model.duplicateServiceProviderName') ?? '') })
            }
            if (!formData.name || formData.name.length > 100) {
                return toast.show({ type: 'warning', message: String(t('model.duplicateServiceProviderNameValidation') ?? '') })
            }
            const [config, errorKey] = formRef.current.getData();
            if (errorKey) {
                return toast.show({ type: 'warning', message: String(`${errorKey} ${t('model.notBeEmpty')}`) })
            }

            const trimmedModels = trimModelNames(formData.models)
            setFormData({ ...formData, models: trimmedModels })

            let hasTTSVoiceError = false
            for (const model of trimmedModels) {
                if (model.model_type === 'tts' && !model.config?.voice) {
                    hasTTSVoiceError = true
                }
            }
            if (hasInvalidModelName(trimmedModels)) {
                return toast.show({ type: 'warning', message: String(t('model.modelNameValidation') ?? '') })
            }
            if (hasDuplicateModelName(trimmedModels)) {
                return toast.show({ type: 'warning', message: String(t('model.modelDuplicate') ?? '') })
            }
            if (hasTTSVoiceError) {
                return toast.show({ type: 'warning', message: String(t('model.voiceTypeRequired') ?? '') })
            }

            const saveData = {
                ...formData,
                models: trimmedModels,
                config
            }

            if (id === -1) {
                await addLLmServer(saveData).then(res => {
                    onAfterSave(res.code === 10803 ? res.msg : t('model.addSuccess'))
                    onBack()
                })
            } else {
                await updateLLmServer(saveData).then(res => {
                    onAfterSave(t('model.updateSuccess'))
                    onBack()
                })
            }
            refetchConfig()
        } catch (error) {
            showApiError(error);
        } finally {
            setIsLoading(false);
        }
    };

    const handleModelDel = () => {
        bsConfirm({
            desc: t('model.deleteConfirmation'),
            onOk(next) {
                return deleteLLmServer(id).then(() => {
                    onAfterSave(t('model.deleteSuccess'));
                    refetchConfig();
                    onBack();
                    next();
                });
            }
        })
    }

    const filterProvider = useCallback((keyword: string, option: { value: string | number, label: string }) => {
        const word = keyword.trim().toLowerCase()
        if (option.label.toLowerCase().includes(word)) return true
        if (option.value !== 'openai_compatible') return false
        const localized = t('model.openaiCompatibleSearchWords').split(',')
        return [...OPENAI_COMPATIBLE_SEARCH_WORDS, ...localized].some(w => w.trim().toLowerCase().includes(word))
    }, [t])

    const _modelProvider = useMemo(() => {
        return id === -1 ? modelProvider : [...modelProvider, bishengModelProvider]
    }, [id])

    const providerInfo = useModelProviderInfo(formData.type)

    if (detailLoading) return <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <Outlined.Loading  className="size-4 animate-spin"/>
    </div>

    if (detailError) return <Alert type="error" live
        description={detailError instanceof Error ? detailError.message : String(t('api_errors:fallback'))}
        actions={[{ label: t('retry', { ns: 'knowledge' }), onClick: () => setDetailReload(value => value + 1) }]}
    />;

    return <div className="relative size-full py-4">
        <div className="flex ml-6 items-center gap-x-3">
            <SharedTooltip content={t('back', { ns: 'bs' })} side="right">
                <SharedButton variant="ghost" size="icon" aria-label={t('back', { ns: 'bs' })} onClick={() => onBack()}>
                    <Outlined.ArrowLeft />
                </SharedButton>
            </SharedTooltip>
            <span>{id === -1 ? t('model.addModel') : t('model.modelConfiguration')}</span>
        </div>
        <div className="mx-auto mt-6 h-[calc(100vh-220px-var(--license-banner-h,0px))] w-full max-w-[720px] overflow-y-auto px-4 pb-10">
            <section className="space-y-4">
                <div className="space-y-2">
                    <Label className="bisheng-label inline-flex items-center">
                        <span>{t('model.providerType')}</span>
                        <ModelFieldHint className="ml-1" content={t('model.providerTypeTip')} />
                    </Label>
                    <Select
                        {...selectLabels}
                        aria-label={t('model.providerType')}
                        disabled={id !== -1}
                        options={_modelProvider
                            .filter(model => model.value != null && model.value !== '')
                            .map(model => ({
                                value: model.value,
                                label: providerLabel(model, t),
                                group: model.group ? t(`model.providerGroups.${model.group}`) : undefined,
                            }))}
                        filterOption={filterProvider}
                        value={formData.type || null}
                        onChange={(val) => { if (val != null) handleTypeChange(val) }}
                    />
                </div>
                <div className="space-y-2">
                    <Label className="bisheng-label inline-flex items-center">
                        <span>{t('model.serviceProviderName')}</span>
                        <span className="text-red-500">*</span>
                        <ModelFieldHint className="ml-1" content={t('model.serviceProviderNameTooltip')} />
                    </Label>
                    <Input value={formData.name} onChange={(e) => {
                        const name = e.target.value
                        setFormData({ ...formData, name })
                        setNameError(!name ? t('model.cannotBeEmpty') : name.length > 100 ? t('model.max100Characters') : '')
                    }}></Input>
                    {nameError && <span className="text-xs text-red-500">{nameError}</span>}
                </div>
                <CustomForm
                    ref={formRef}
                    showDefault={id === -1}
                    provider={formData.type}
                    formData={formData.config}
                    modelTypes={formData.models.map(model => model.model_type)}
                    providerName={providerLabel(_modelProvider.find(el => el.value === formData.type), t)}
                    apiKeySite={providerInfo?.apiKeyUrl}
                />
            </section>
            <div className={formData.type ? 'visible' : 'invisible'}>
                <section className="mt-6 space-y-4 border-t pt-6">
                    <h3 className="text-sm font-medium">{t('model.sectionUsage')}</h3>
                    <div className="space-y-3">
                        <div className="flex items-center justify-between gap-4">
                            <Label className="bisheng-label inline-flex items-center">
                                <span>{t('model.dailyCallLimit')}</span>
                                <ModelFieldHint className="ml-1" content={t('model.dailyCallLimitTip')} />
                            </Label>
                            <Switch checked={formData.limit_flag} onCheckedChange={(val) => setFormData(form => ({ ...form, limit_flag: val }))} />
                        </div>
                        {formData.limit_flag && (
                            <div className="flex flex-nowrap items-center gap-2 text-sm text-text-3">
                                <div className="w-28 shrink-0">
                                    <Input type="number" size="medium" min={1} value={formData.limit} aria-label={t('model.dailyCallLimit')} onChange={(e) => { if (!isNumberDraftWithinBounds(e.currentTarget.value, { min: 1 })) return; return setFormData({ ...formData, limit: Number(e.target.value) }); }}></Input>
                                </div>
                                <span className="shrink-0 whitespace-nowrap">{t('model.timesPerDay')}</span>
                            </div>
                        )}
                    </div>
                    {showShareToggle && (
                        <div className="flex items-center justify-between gap-4">
                            <Label className="bisheng-label inline-flex items-center">
                                <span>{t('model.shareToChildren')}</span>
                                <ModelFieldHint className="ml-1" content={t('model.shareToChildrenTip')} />
                            </Label>
                            <Switch
                                checked={formData.share_to_children}
                                onCheckedChange={(val) => setFormData(form => ({ ...form, share_to_children: val }))}
                            />
                        </div>
                    )}
                </section>
                <section className="mt-6 border-t pt-6">
                    <div className="flex items-center justify-between gap-4">
                        <h3 className="text-sm font-medium">{t('model.model')}</h3>
                        {providerInfo && <a href={providerInfo.modelUrl} target="_blank" rel="noreferrer" className="shrink-0 text-xs text-primary hover:underline">
                            {t('model.visitOfficialWebsiteToViewAvailableModels')}
                        </a>}
                    </div>
                    <div className="mt-2 space-y-3">
                        {
                            formData.models.map((m, i) => (
                                <ModelItem
                                    key={m.id}
                                    data={m}
                                    type={formData.type}
                                    onInput={(name, type) => handleModelChange(name, type, i)}
                                    onConfig={(config) => handleModelConfig(config, i)}
                                    onDelete={() => handleDelete(i)}
                                />
                            ))
                        }
                        <Button className="w-full border-dashed border-border" variant="outlined" onClick={handleAddModel} disabled={(String((formData.limit) ?? '') !== '' && (!Number.isFinite(Number(formData.limit)) || Number(formData.limit) < 1))} color="default">
                            <Outlined.Plus />
                            <span>{t('model.addModel')}</span>
                        </Button>
                    </div>
                </section>
            </div>
        </div>
        <div className="absolute right-0 bottom-0 p-4 flex gap-4">
            {id !== -1 && <Button variant="outlined" onClick={handleModelDel} color="danger">{t('model.delete')}</Button>}
            <Button variant="outlined" onClick={() => onBack()} color="default">{t('model.cancel')}</Button>
            <Button loading={isLoading} onClick={handleSave} disabled={((String((formData.limit) ?? '') !== '' && (!Number.isFinite(Number(formData.limit)) || Number(formData.limit) < 1))) || (Boolean(isLoading) || (!formData.type))}>
                {t('model.save')}
            </Button>
        </div>
    </div>
}

const useSelectModel = () => {
    const modelsRef = useRef<any>(null)

    const loadData = async () => {
        try {
            const response = await fetch(__APP_ENV__?.BASE_URL + '/models/data.json');
            if (!response.ok) {
                throw new Error('Failed to fetch data');
            }
            return await response.json();
        } catch (error) {
            console.error('Failed to load commitments:', error);
            return { title: '', commitments: [] };
        }
    }

    useEffect(() => {
        loadData().then(
            res => modelsRef.current = res
        )
    }, [])

    return (type) => {
        return (modelsRef.current?.[type] || [])
            .map(item => ({
                ...item,
                id: generateUUID(4)
            }))
    }
}
