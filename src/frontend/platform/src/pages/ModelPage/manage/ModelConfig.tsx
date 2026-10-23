// @ts-strict-ignore
import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button, LoadButton } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { addLLmServer, deleteLLmServer, getLLmServerDetail, updateLLmServer } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useAdminScope } from "@/hooks/useAdminScope";
import { ArrowLeft, Plus } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CustomForm from "./CustomForm";
import { canShareToChildren, isGlobalSuperUser } from "./permissions";
import { useLinsightConfig } from "./tabs/WorkbenchModel";
import { useModelProviderInfo } from "./useLink";
import { ModelItem } from "./ModelItem";
import { hasDuplicateModelName, hasInvalidModelName, trimModelNames } from "./modelNameTrim";

export const modelProvider = [
    { "name": "OpenAI", "value": "openai" },
    { "name": "Azure OpenAI", "value": "azure_openai" },
    { "name": "Ollama", "value": "ollama" },
    { "name": "xinference", "value": "xinference" },
    { "name": "llamacpp", "value": "llamacpp" },
    { "name": "vllm", "value": "vllm" },
    { "name": "", "labelKey": "model.providerNames.qwen", "value": "qwen" },
    { "name": "DeepSeek", "value": "deepseek" },
    { "name": "", "labelKey": "model.providerNames.silicon", "value": "silicon" },
    { "name": "", "labelKey": "model.providerNames.volcengine", "value": "volcengine" },
    { "name": "", "labelKey": "model.providerNames.zhipu", "value": "zhipu" },
    { "name": "", "labelKey": "model.providerNames.spark", "value": "spark" },
    { "name": "", "labelKey": "model.providerNames.tencent", "value": "tencent" },
    { "name": "", "labelKey": "model.providerNames.moonshot", "value": "moonshot" },
    { "name": "", "labelKey": "model.providerNames.qianfan", "value": "qianfan" },
    { "name": "Minimax", "value": "minimax" },
    { "name": "Anthropic", "value": "anthropic" },
    { "name": "MindIE", "value": "MindIE" },
]
const bishengModelProvider = { "name": "bishengRT", "value": "bisheng_rt" }

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
    const { refetch: refetchConfig } = useLinsightConfig();
    const { user } = useContext(userContext);
    const { appConfig } = useContext(locationContext);

    const [formData, setFormData] = useState({ ...defaultForm })
    const [nameError, setNameError] = useState('')

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
        if (id === -1) return
        getLLmServerDetail(id).then(res => {
            setFormData(res)
        })
    }, [id])

    const getModelsByType = useSelectModel()
    const handleTypeChange = (val) => {
        const name = onGetName(providerLabel(_modelProvider.find(el => el.value === val), t))
        const models = getModelsByType(val)
        setFormData({ ...formData, type: val, name, models })
    }

    const handleAddModel = () => {
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

    const { message } = useToast()
    const formRef = useRef(null)
    const [isLoading, setIsLoading] = useState(false);
    const handleSave = async () => {
        setIsLoading(true)
        try {
            const exists = onBerforSave(formData.id, formData.name)
            if (exists) {
                return message({
                    variant: 'warning',
                    description: t('model.duplicateServiceProviderName')
                })
            }
            if (!formData.name || formData.name.length > 100) {
                return message({
                    variant: 'warning',
                    description: t('model.duplicateServiceProviderNameValidation')
                })
            }
            const [config, errorKey] = formRef.current.getData();
            if (errorKey) {
                return message({
                    variant: 'warning',
                    description: `${errorKey} ${t('model.notBeEmpty')}`
                })
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
                return message({
                    variant: 'warning',
                    description: t('model.modelNameValidation')
                })
            }
            if (hasDuplicateModelName(trimmedModels)) {
                return message({
                    variant: 'warning',
                    description: t('model.modelDuplicate')
                })
            }
            if (hasTTSVoiceError) {
                return message({
                    variant: 'warning',
                    description: t('model.voiceTypeRequired')
                })
            }

            const saveData = {
                ...formData,
                models: trimmedModels,
                config
            }

            if (id === -1) {
                await captureAndAlertRequestErrorHoc(addLLmServer(saveData).then(res => {
                    onAfterSave(res.code === 10803 ? res.msg : t('model.addSuccess'))
                    onBack()
                }))
            } else {
                await captureAndAlertRequestErrorHoc(updateLLmServer(saveData).then(res => {
                    onAfterSave(t('model.updateSuccess'))
                    onBack()
                }))
            }
            refetchConfig()
        } catch (error) {
            console.error('Save error:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const handleModelDel = () => {
        bsConfirm({
            desc: t('model.deleteConfirmation'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteLLmServer(id).then(res => {
                    onAfterSave(t('model.deleteSuccess'))
                    refetchConfig()
                }))
                onBack()
                next()
            }
        })
    }

    const _modelProvider = useMemo(() => {
        return id === -1 ? modelProvider : [...modelProvider, bishengModelProvider]
    }, [id])

    const providerInfo = useModelProviderInfo(formData.type)

    if (!formData) return <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return <div className="relative size-full py-4">
        <div className="flex ml-6 items-center gap-x-3">
            <ShadTooltip content={t('back', { ns: 'bs' })} side="right">
                <button className="extra-side-bar-buttons w-[36px]" onClick={() => onBack()}>
                    <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                </button>
            </ShadTooltip>
            <span>{id === -1 ? t('model.addModel') : t('model.modelConfiguration')}</span>
        </div>
        <div className="mx-auto mt-6 h-[calc(100vh-220px-var(--license-banner-h,0px))] w-full max-w-[720px] overflow-y-auto px-4 pb-10">
            <section className="space-y-4">
                <h3 className="text-sm font-medium">{t('model.sectionConnection')}</h3>
                <div className="space-y-2">
                    <Label className="bisheng-label">
                        <span>{t('model.providerType')}</span>
                        <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.providerTypeTip')} />
                    </Label>
                    <Select value={formData.type} disabled={id !== -1} onValueChange={handleTypeChange}>
                        <SelectTrigger>
                            <SelectValue placeholder="" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {_modelProvider.map((model => <SelectItem key={model.value} value={model.value}>{providerLabel(model, t)}</SelectItem>))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                <div className="space-y-2">
                    <Label className="bisheng-label">
                        <span>{t('model.serviceProviderName')}</span>
                        <span className="text-red-500">*</span>
                        <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.serviceProviderNameTooltip')} />
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
                    providerName={providerLabel(_modelProvider.find(el => el.value === formData.type), t)}
                    apiKeySite={providerInfo?.apiKeyUrl}
                />
            </section>
            <div className={formData.type ? 'visible' : 'invisible'}>
                <section className="mt-6 space-y-4 border-t pt-6">
                    <h3 className="text-sm font-medium">{t('model.sectionUsage')}</h3>
                    <div className="space-y-3">
                        <div className="flex items-center justify-between gap-4">
                            <Label className="bisheng-label">
                                <span>{t('model.dailyCallLimit')}</span>
                                <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.dailyCallLimitTip')} />
                            </Label>
                            <Switch checked={formData.limit_flag} onCheckedChange={(val) => setFormData(form => ({ ...form, limit_flag: val }))} />
                        </div>
                        {formData.limit_flag && (
                            <div className="flex items-center gap-2 whitespace-nowrap text-sm text-muted-foreground">
                                <span>{t('model.dailyLimitPrefix')}</span>
                                <div className="w-28 shrink-0">
                                    <Input type="number" min={1} value={formData.limit}
                                        onChange={(e) => setFormData({ ...formData, limit: Number(e.target.value) })}
                                        className="h-8"
                                    ></Input>
                                </div>
                                <span>{t('model.dailyLimitSuffix')}</span>
                            </div>
                        )}
                    </div>
                    {showShareToggle && (
                        <div className="flex items-center justify-between gap-4">
                            <Label className="bisheng-label">
                                <span>{t('model.shareToChildren')}</span>
                                <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.shareToChildrenTip')} />
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
                        <Button className="w-full border-dashed border-border" variant="outline" onClick={handleAddModel}>
                            <Plus className="size-5 text-primary mr-1" />
                            <span>{t('model.addModel')}</span>
                        </Button>
                    </div>
                </section>
            </div>
        </div>
        <div className="absolute right-0 bottom-0 p-4 flex gap-4">
            {id !== -1 && <Button className="px-8" variant="destructive" onClick={handleModelDel}>{t('model.delete')}</Button>}
            <Button className="px-8" variant="outline" onClick={() => onBack()}>{t('model.cancel')}</Button>
            <LoadButton
                className="px-16"
                disabled={!formData.type}
                loading={isLoading}
                onClick={handleSave}
            >
                {isLoading ? t('model.modelStatusChecking') : t('model.save')}
            </LoadButton>
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
