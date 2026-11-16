// @ts-strict-ignore
import { Button, notification } from '@bisheng/ui';
import { LoadingIcon } from "@/components/bs-icons/loading";


import { DialogClose,DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from '@/components/bs-ui/label';

import { getToolsApi } from '@/controllers/API/tools';
import { getWebSearchSettings, putWebSearchSettings, WebSearchSecret } from '@/controllers/API/webSearch';
import { CustomWebSearch } from './CustomWebSearch';
import { normalizeSearchMapping } from './customSearchMapping';
import { useEffect,useRef,useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField,SelectField } from "./InputField";

const defaultToolParams = {
    bing: {
        api_key: '',
        base_url: 'https://api.bing.microsoft.com/v7.0/search'
    },
    bocha: {
        api_key: '',
        base_url: ''
    },
    jina: {
        api_key: '',
        base_url: ''
    },
    serp: {
        api_key: '',
        engine: 'baidu',
        base_url: ''
    },
    tavily: {
        api_key: '',
        base_url: ''
    },
    cloudsway: {
        api_key: '',
        endpoint: '',
        base_url: ''
    },
    searXNG: {
        server_url: ''
    },
    deepseek: {
        api_key: '',
        base_url: ''
    },
};

interface WebSearchFormProps {
    isApi?: boolean;
    toolId?: string;
    onSaved?: () => void;
    onSavingChange?: (saving: boolean) => void;
}

const WebSearchForm = ({ isApi = false, toolId, onSaved, onSavingChange }: WebSearchFormProps) => {
    const { t } = useTranslation();
    const tRef = useRef(t);
    tRef.current = t;
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const toolIdRef = useRef('');
    const [enabled, setEnabled] = useState(true);
    const [prompt, setPrompt] = useState('');
    const [revision, setRevision] = useState('');
    const [secretConfigured, setSecretConfigured] = useState(false);
    const [secret, setSecret] = useState<WebSearchSecret>({ action: 'keep' });
    const [reload, setReload] = useState(0);
    const closeRef = useRef<HTMLButtonElement | null>(null);

    const [allToolsConfig, setAllToolsConfig] = useState<Record<string, any>>({
        ...defaultToolParams,
    });

    const [persistedProviders, setPersistedProviders] = useState<string[]>([]);
    const [selectedTool, setSelectedTool] = useState<string>('bing');
    const [formErrors, setFormErrors] = useState({});

    useEffect(() => {
        let active = true;
        const load = async () => {
            setLoading(true);
            setRevision('');
            try {
                let id = toolId;
                if (!id && isApi) {
                    const tools = await getToolsApi('default');
                    id = tools.find((item: any) => (item.children || []).some((child: any) => child.tool_key === 'web_search'))?.id;
                }
                if (!id) throw new Error('Missing tool');
                const settings = await getWebSearchSettings(String(id));
                if (!active) return;
                toolIdRef.current = String(id);
                setSelectedTool(settings.type || 'bing');
                setEnabled(settings.enabled);
                setPrompt(settings.prompt || '');
                const providers = { ...defaultToolParams, ...settings.providers };
                const custom = settings.providers.custom as { mapping?: Record<string, string> } | undefined;
                if (custom) providers.custom = { ...custom, mapping: normalizeSearchMapping(custom.mapping) };
                setAllToolsConfig(providers);
                setPersistedProviders(Object.keys(settings.providers));
                setRevision(settings.revision);
                setSecretConfigured(settings.custom_secret_configured);
                setSecret({ action: 'keep' });
            } catch {
                if (active) notification.open({ type: 'error', title: String(tRef.current('failed')), description: String(tRef.current('chatConfig.webSearch.loadFailed')) });
            } finally {
                if (active) setLoading(false);
            }
        };
        void load();
        return () => { active = false; };
    }, [isApi, toolId, reload]);

    const validationRules = {
        bing: {
            base_url: (value) => !(value || defaultToolParams.bing.base_url) && 'Bing Search URL ' + t('chatConfig.errors.required')
        },
        bocha: {
            api_key: (value) => !value && 'API Key ' + t('chatConfig.errors.required')
        },
        jina: {
            api_key: (value) => !value && 'API Key ' + t('chatConfig.errors.required')
        },
        serp: {
            api_key: (value) => !value && 'API Key ' + t('chatConfig.errors.required'),
            engine: (value) => !(value || defaultToolParams.serp.engine) && 'engine ' + t('chatConfig.errors.required')
        },
        tavily: {
            api_key: (value) => !value && 'API Key ' + t('chatConfig.errors.required')
        },
        cloudsway: {
            api_key: (value) => !value && 'AccessKey ' + t('chatConfig.errors.required'),
            endpoint: (value) => !value && 'Endpoint ' + t('chatConfig.errors.required')
        },
        searXNG: {
            server_url: (value) => !(value || allToolsConfig.searXNG?.base_url) && 'The server address cannot be empty'
        },
        deepseek: {
            api_key: (value) => !value && 'API Key ' + t('chatConfig.errors.required')
        }
    };

    const handleToolChange = (tool) => {
        setSelectedTool(tool);
        setFormErrors({});
    };

    const handleParamChange = (e) => {
        const { name, value } = e.target;
        setPersistedProviders(prev => prev.includes(selectedTool) ? prev : [...prev, selectedTool]);
        setAllToolsConfig(prev => ({
            ...prev,
            [selectedTool]: {
                ...prev[selectedTool],
                [name]: value,
                ...(selectedTool === 'searXNG' && name === 'server_url' && value === '' && 'base_url' in (prev[selectedTool] || {}) ? { base_url: '' } : {})
            }
        }));

        setFormErrors(prev => ({
            ...prev,
            [name]: undefined
        }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const errors = {} as Record<string, string>;
        const currentToolRules = (validationRules as any)[selectedTool] || {};

        Object.keys(currentToolRules).forEach(key => {
            const error = currentToolRules[key]((allToolsConfig as any)[selectedTool]?.[key]);
            if (error) {
                errors[key] = error;
            }
        });

        if (Object.keys(errors).length > 0) {
            setFormErrors(errors);
            return;
        }

        if (selectedTool === 'custom') {
            const custom = allToolsConfig.custom;
            const operation = custom?.operation;
            const mapping = custom?.mapping;
            if (!custom?.proof?.key_id || !custom?.proof?.ciphertext) {
                notification.open({ type: 'error', title: String(t('failed')), description: String(t('chatConfig.webSearch.proofRequired')) });
                return;
            }
            if (!operation?.server || !operation?.method || !operation?.path || !operation?.query_parameter?.name || !mapping?.title || !mapping?.url || !mapping?.snippet || (operation?.auth?.location !== 'none' && (!operation?.auth?.name || (secret.action !== 'replace' && !secretConfigured)))) {
                notification.open({ type: 'error', title: String(t('failed')), description: String(t('chatConfig.webSearch.requiredFields')) });
                return;
            }
        }
        try {
            setSaving(true);
            onSavingChange?.(true);
            const providers = Object.fromEntries(persistedProviders.map(key => [key, allToolsConfig[key]]));
            if (selectedTool in defaultToolParams && !(selectedTool in providers)) providers[selectedTool] = allToolsConfig[selectedTool];
            if (selectedTool === 'bing' && providers.bing && !providers.bing.base_url) providers.bing = { ...providers.bing, base_url: defaultToolParams.bing.base_url };
            if (selectedTool === 'serp' && providers.serp && !providers.serp.engine) providers.serp = { ...providers.serp, engine: defaultToolParams.serp.engine };
            if (providers.custom) providers.custom = { ...providers.custom, mapping: normalizeSearchMapping(providers.custom.mapping) };
            await putWebSearchSettings(toolIdRef.current, {
                revision, enabled, type: selectedTool, prompt, providers, custom_secret: selectedTool === 'custom' ? secret : { action: 'keep' },
            });
            setSecret({ action: 'keep' });
            notification.open({ type: 'success', title: String(t('skills.saveSuccessful')), description: '' });
            onSaved?.();
            closeRef.current?.click();
        } catch {
            notification.open({ type: 'error', title: String(t('failed')), description: String(t('chatConfig.webSearch.saveFailed')) });
        } finally {
            setSaving(false);
            onSavingChange?.(false);
        }
    };

    const renderParams = () => {

        const currentTool: any = ((allToolsConfig as any)[selectedTool] as any) || ({} as any);
        const currentToolMap: Record<string, any> = currentTool as Record<string, any>;

        if (!currentTool) return null;

        const baseUrlField = (
            <InputField
                label="Base URL"
                name="base_url"
                value={currentToolMap['base_url'] || ''}
                onChange={handleParamChange}
                error={(formErrors as any).base_url}
                id={`${selectedTool}-base-url`}
            />
        );

        switch (selectedTool) {
            case 'custom':
                return <CustomWebSearch toolId={toolIdRef.current} value={allToolsConfig.custom} onChange={(value) => { setPersistedProviders(prev => prev.includes('custom') ? prev : [...prev, 'custom']); setAllToolsConfig(prev => ({ ...prev, custom: value })); }} secret={secret} onSecretChange={setSecret} secretConfigured={secretConfigured} />;
            case 'bing':
                return (
                    <>
                        <InputField
                            required
                            label="Bing Subscription Key"
                            type="password"
                            name="api_key"
                            value={currentToolMap['api_key'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).api_key}
                            id="bing-api-key"
                        />
                        <InputField
                            required
                            label="Bing Search URL"
                            name="base_url"
                            value={currentToolMap['base_url'] || defaultToolParams.bing.base_url}
                            onChange={handleParamChange}
                            error={(formErrors as any).base_url}
                            id="bing-base-url"
                        />
                    </>
                );
            case 'bocha':
                return (
                    <>
                        <InputField
                            required
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentToolMap['api_key'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).api_key}
                            id="bocha-api-key"
                        />
                        {baseUrlField}
                    </>
                );
            case 'jina':
                return (
                    <>
                        <InputField
                            required
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentToolMap['api_key'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).api_key}
                            id="jina-api-key"
                        />
                        {baseUrlField}
                    </>
                );
            case 'serp':
                return (
                    <>
                        <InputField
                            required
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentToolMap['api_key'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).api_key}
                            id="serp-api-key"
                        />
                        <InputField
                            required
                            label="engine"
                            name="engine"
                            value={currentToolMap['engine'] || 'baidu'}
                            onChange={handleParamChange}
                            error={(formErrors as any).engine}
                            id="serp-engine"
                        />
                        {baseUrlField}
                    </>
                );
            case 'tavily':
                return (
                    <>
                        <InputField
                            required
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentToolMap['api_key'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).api_key}
                            id="tavily-api-key"
                        />
                        {baseUrlField}
                    </>
                );
            case 'cloudsway':
                return (
                    <>
                        {/* Cloudsway issues an AccessKey and an Endpoint id; the console names are used as labels */}
                        <InputField
                            required
                            label="AccessKey"
                            type="password"
                            name="api_key"
                            value={currentToolMap['api_key'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).api_key}
                            id="cloudsway-api-key"
                            tooltip={t('chatConfig.webSearch.cloudswayAccessKeyTip')}
                        />
                        <InputField
                            required
                            label="Endpoint"
                            name="endpoint"
                            value={currentToolMap['endpoint'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).endpoint}
                            id="cloudsway-endpoint"
                            tooltip={t('chatConfig.webSearch.cloudswayEndpointTip')}
                        />
                        {baseUrlField}
                    </>
                );
            case 'deepseek':
                return (
                    <>
                        <InputField
                            required
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentToolMap['api_key'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as Record<string, string>).api_key}
                            id="deepseek-api-key"
                        />
                        {/* Empty base_url falls back to this endpoint on the backend */}
                        <InputField
                            label="Base URL"
                            name="base_url"
                            value={currentToolMap['base_url'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as Record<string, string>).base_url}
                            id="deepseek-base-url"
                            placeholder="https://api.deepseek.com/v1/tools/search"
                        />
                    </>
                );
            case 'searXNG':
                return (
                    <InputField
                        required
                        label={t('chatConfig.webSearch.serverUrl')}
                        name="server_url"
                        value={currentToolMap['server_url'] || currentToolMap['base_url'] || ''}
                        onChange={handleParamChange}
                        error={(formErrors as any).server_url}
                        id="searxng-server-url"
                        placeholder={t('chatConfig.webSearch.serverUrlPlaceholder')}
                    />
                );
            default:
                return null;
        }
    };

    if (loading) {
        return (
            <div className="flex h-40 items-center justify-center">
                <LoadingIcon />
            </div>
        );
    }

    return (
        <>
            <form onSubmit={handleSubmit} className="flex max-h-[75vh] flex-col gap-4 overflow-y-auto">
                {/* Hide the close button for programmatic closing of the pop-up window after successful submission. */}
                <DialogClose asChild>
                    <button ref={closeRef} className="hidden" />
                </DialogClose>
                <SelectField
                    label={t('chatConfig.webSearch.engine')}
                    value={selectedTool}
                    onChange={handleToolChange}
                    options={[
                        { value: 'custom', label: t('chatConfig.webSearch.custom') },
                        { value: 'bing', label: t('chatConfig.webSearch.bing') },
                        { value: 'bocha', label: t('chatConfig.webSearch.bocha') },
                        { value: 'jina', label: t('chatConfig.webSearch.jina') },
                        { value: 'serp', label: t('chatConfig.webSearch.serp') },
                        { value: 'tavily', label: t('chatConfig.webSearch.tavily') },
                        { value: 'searXNG', label: t('chatConfig.webSearch.searXNG') },
                        { value: 'cloudsway', label: t('chatConfig.webSearch.cloudsway') },
                        { value: 'deepseek', label: t('chatConfig.webSearch.deepseek') },
                    ]}
                    id="search-tool-selector"
                    name="search_tool"
                />

                <div className="space-y-4">
                    <Label className="bisheng-label">{t('chatConfig.webSearch.config')}</Label>
                    {renderParams()}
                </div>

                <DialogFooter>
                    <DialogClose asChild>
                        <Button variant="outlined" type="button" color="default">
                            {t('build.cancel')}
                        </Button>
                    </DialogClose>
                    <Button type="button" variant="outlined" color="default" onClick={() => setReload(value => value + 1)}>{t('chatConfig.webSearch.reload')}</Button>
                    <Button type="submit" disabled={saving || !revision}>
                        {t('build.confirm')}
                    </Button>
                </DialogFooter>
            </form>
        </>

    );
};

export default WebSearchForm;
