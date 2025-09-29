import { useEffect, useRef, useState } from 'react';
import { useTranslation } from "react-i18next";
import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from '@/components/bs-ui/label';
import { toast } from '@/components/bs-ui/toast/use-toast';
import { getAssistantToolsApi, updateAssistantToolApi } from "@/controllers/API/assistant";
import { InputField, SelectField } from "./InputField";
import { LoadingIcon } from '@/components/bs-icons/loading';

const defaultToolParams = {
    bing: {
        api_key: '',
        base_url: 'https://api.bing.microsoft.com/v7.0/search'
    },
    bocha: {
        api_key: ''
    },
    jina: {
        api_key: ''
    },
    serp: {
        api_key: '',
        engine: 'baidu'
    },
    tavily: {
        api_key: ''
    },
    cloudsway: {
        api_key: '',
        endpoint: ''
    },
    searXNG: {
        server_url: ''
    },
};

interface WebSearchFormProps {
    formData?: any;
    onSubmit?: (config: any) => void;
    isApi?: boolean;
}

const WebSearchForm = ({ formData, onSubmit, isApi = false }: WebSearchFormProps) => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const toolIdRef = useRef('');
    const [enabled, setEnabled] = useState(true);
    const [prompt, setPrompt] = useState('');
    const closeRef = useRef<HTMLButtonElement | null>(null);

    const [allToolsConfig, setAllToolsConfig] = useState<Record<string, any>>({
        ...defaultToolParams,
    });

    const [selectedTool, setSelectedTool] = useState<string>('bing');
    const [formErrors, setFormErrors] = useState({});

    // 初始化：isApi 为 true 走接口获取；否则使用父级 formData
    useEffect(() => {
        const initFromApi = async () => {
            try {
                const res = await getAssistantToolsApi('default');
                const webSearchTool = res.find((item: any) => item.name === '联网搜索');
                if (webSearchTool) {
                    toolIdRef.current = webSearchTool.id;
                    if (webSearchTool.extra) {
                        try {
                            const extraData = JSON.parse(webSearchTool.extra);
                            setSelectedTool(extraData.type || 'bing');
                            setEnabled(extraData.enabled ?? true);
                            setPrompt(extraData.prompt ?? '');
                            setAllToolsConfig({
                                ...defaultToolParams,
                                ...(extraData.config || {}),
                            });
                        } catch (e) {}
                    }
                }
            } catch (error: any) {
                toast({
                    title: t('failed'),
                    description: error?.message || '',
                    variant: 'error',
                });
            } finally {
                setLoading(false);
            }
        };

        const initFromProps = () => {
            const mergedConfig = {
                ...defaultToolParams,
                ...(formData?.config || {}),
            } as Record<string, any>;
            setAllToolsConfig(mergedConfig);
            setSelectedTool(formData?.type || 'bing');
            setEnabled(formData?.enabled ?? true);
            setPrompt(formData?.prompt ?? '');
            setLoading(false);
        };

        if (isApi) {
            initFromApi();
        } else {
            initFromProps();
        }
    }, [isApi, formData]);

    const validationRules = {
        bing: {
            api_key: (value) => !value && 'Bing Subscription Key 不能为空',
            base_url: (value) => !value && 'Bing Search URL 不能为空'
        },
        bocha: {
            api_key: (value) => !value && 'API Key 不能为空'
        },
        jina: {
            api_key: (value) => !value && 'API Key 不能为空'
        },
        serp: {
            api_key: (value) => !value && 'API Key 不能为空',
            engine: (value) => !value && 'engine 不能为空'
        },
        tavily: {
            api_key: (value) => !value && 'API Key 不能为空'
        },
        cloudsway: {
            api_key: (value) => !value && 'API Key 不能为空',
            endpoint: (value) => !value && 'endpoint 不能为空'
        },
        searXNG: {
            server_url: (value) => !value && '服务器地址不能为空'
        }
    };

    const handleToolChange = (tool) => {
        setSelectedTool(tool);
        setFormErrors({});
    };

    const handleParamChange = (e) => {
        const { name, value } = e.target;
        setAllToolsConfig(prev => ({
            ...prev,
            [selectedTool]: {
                ...prev[selectedTool],
                [name]: value
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

        const typedConfig = {
            bing: (allToolsConfig as any).bing || defaultToolParams.bing,
            bocha: (allToolsConfig as any).bocha || defaultToolParams.bocha,
            jina: (allToolsConfig as any).jina || defaultToolParams.jina,
            serp: (allToolsConfig as any).serp || defaultToolParams.serp,
            tavily: (allToolsConfig as any).tavily || defaultToolParams.tavily,
            cloudsway: (allToolsConfig as any).cloudsway,
            searXNG: (allToolsConfig as any).searXNG,
        };

        const newConfig = {
            enabled,
            type: selectedTool,
            config: typedConfig,
            prompt,
        };
        try {
            if (isApi) {
                if (toolIdRef.current) {
                    await updateAssistantToolApi(toolIdRef.current, newConfig);
                }
                toast({
                    title: t('skills.saveSuccessful'),
                    description: '',
                    variant: 'success',
                });
                // 提交成功后关闭弹窗
                closeRef.current?.click();
            } else {
                onSubmit?.(newConfig);
            }
        } catch (error: any) {
            toast({
                title: t('failed'),
                description: error?.message || '',
                variant: 'error',
            });
        }
    };

    const renderParams = () => {

        const currentTool: any = ((allToolsConfig as any)[selectedTool] as any) || ({} as any);
        const currentToolMap: Record<string, any> = currentTool as Record<string, any>;
        console.log(currentTool, 111);

        if (!currentTool) return null;

        switch (selectedTool) {
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
                );
            case 'jina':
                return (
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
                    </>
                );
            case 'tavily':
                return (
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
                );
            case 'cloudsway':
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
                            id="cloudsway-api-key"
                        />
                        <InputField
                            required
                            label="endpoint"
                            name="endpoint"
                            value={currentToolMap['endpoint'] || ''}
                            onChange={handleParamChange}
                            error={(formErrors as any).endpoint}
                            id="cloudsway-endpoint"
                        />
                        </>
                    );
            case 'searXNG':
                return (
                    <InputField
                        required
                        label={t('chatConfig.webSearch.serverUrl')}
                        name="server_url"
                        value={currentToolMap['server_url'] || ''}
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

    if (isApi && loading) {
        return (
            <div className="flex h-40 items-center justify-center">
                <LoadingIcon />
            </div>
        );
    }

    return (
        <>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* 隐藏关闭按钮，供提交成功后程序化关闭弹窗 */}
            <DialogClose asChild>
                <button ref={closeRef} className="hidden" />
            </DialogClose>
            <SelectField
                label={t('chatConfig.webSearch.engine')}
                value={selectedTool}
                onChange={handleToolChange}
                options={[
                    { value: 'bing', label: t('chatConfig.webSearch.bing') },
                    { value: 'bocha', label: t('chatConfig.webSearch.bocha') },
                    { value: 'jina', label: t('chatConfig.webSearch.jina') },
                    { value: 'serp', label: t('chatConfig.webSearch.serp') },
                    { value: 'tavily', label: t('chatConfig.webSearch.tavily') },
                    { value: 'searXNG', label: t('chatConfig.webSearch.searXNG') },
                    { value: 'cloudsway', label: t('chatConfig.webSearch.cloudsway') },
                ]}
                id="search-tool-selector"
                name="search_tool"
            />

            <div className="space-y-4">
                <Label className="bisheng-label">{t('chatConfig.webSearch.config')}</Label>
                {renderParams()}
            </div>

            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('build.cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit" disabled={isApi && loading}>
                    {t('build.confirm')}
                </Button>
            </DialogFooter>
        </form>
        </>
    
    );
};

export default WebSearchForm;