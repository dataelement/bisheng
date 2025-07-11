import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useEffect, useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField, SelectField } from "./InputField";
import { Label } from '@/components/bs-ui/label';
import { useWebSearchStore } from '../webSearchStore'
import { toast, useToast } from '@/components/bs-ui/toast/use-toast';

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
        engine: ''
    },
    tavily: {
        api_key: ''
    },
};

const WebSearchForm = ({ formData, onSubmit, errors = {} }) => {
    const { t } = useTranslation();
    const { toast } = useToast();
    const { config: webSearchData, setConfig } = useWebSearchStore();

    const [allToolsConfig, setAllToolsConfig] = useState(() => {
        return {
            bing: {
                ...defaultToolParams.bing,
                ...(webSearchData?.bing || {})
            },
            bocha: {
                ...defaultToolParams.bocha,
                ...(webSearchData?.bocha || {})
            },
            jina: {
                ...defaultToolParams.jina,
                ...(webSearchData?.jina || {})
            },
            serp: {
                ...defaultToolParams.serp,
                ...(webSearchData?.serp || {})
            },
            tavily: {
                ...defaultToolParams.tavily,
                ...(webSearchData?.tavily || {})
            },
        };
    });

    const [selectedTool, setSelectedTool] = useState(webSearchData?.tool || 'bing');
    const [formErrors, setFormErrors] = useState({});

    const handleToolChange = (tool) => {
        setSelectedTool(tool);
    };
    useEffect(() => {
        if (webSearchData) {
            setAllToolsConfig({
                bing: { ...defaultToolParams.bing, ...webSearchData.bing },
                bocha: { ...defaultToolParams.bocha, ...webSearchData.bocha },
                jina: {
                    ...defaultToolParams.jina,
                    ...webSearchData?.jina
                },
                serp: {
                    ...defaultToolParams.serp,
                    ...webSearchData?.serp
                },
                tavily: {
                    ...defaultToolParams.tavily,
                    ...webSearchData?.tavily
                },
            });
            setSelectedTool(webSearchData.tool || 'bing');
        }
    }, [webSearchData]);
    const handleParamChange = (e) => {
        const { name, value } = e.target;
        setAllToolsConfig(prev => ({
            ...prev,
            [selectedTool]: {
                ...prev[selectedTool],
                [name]: value
            }
        }));
    };

    const handleSubmit = (e) => {
        e.preventDefault();

        const newConfig = {
            tool: selectedTool,
            ...allToolsConfig
        };

        try {
            setConfig(newConfig);
            console.log('提交的数据:', newConfig);

            toast({
                title: "保存成功",
                variant: "success",
            });
            onSubmit?.(newConfig);
        } catch (error) {
            toast({
                title: "保存失败",
                description: error.message,
                variant: "error",
            });
        }
    };

    const renderParams = () => {
        const currentTool = allToolsConfig[selectedTool];
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
                            placeholder={t('build.enterSubscriptionKey')}
                            value={currentTool?.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="bing-api-key"
                        />
                        <InputField
                            required
                            label="Bing Search URL"
                            name="base_url"
                            placeholder={t('build.enterSearchUrl')}
                            value={currentTool?.base_url || defaultToolParams.bing.base_url}
                            onChange={handleParamChange}
                            error={formErrors.base_url}
                            id="bing-base-url"
                        />
                    </>
                );
            case 'bocha':
                return (
                    <InputField
                        required
                        label="Bocha API Key"
                        type="password"
                        name="api_key"
                        placeholder={t('build.enterApiKey')}
                        value={currentTool?.api_key || ''}
                        onChange={handleParamChange}
                        error={formErrors.api_key}
                        id="bocha-api-key"
                    />
                );
            case 'jina':
                return (
                    <InputField
                        required
                        label="Jina API Key"
                        type="password"
                        name="api_key"
                        placeholder={t('build.enterApiKey')}
                        value={currentTool?.api_key || ''}
                        onChange={handleParamChange}
                        error={formErrors.api_key}
                        id="jina-api-key"
                    />
                );
            case 'serp':
                return (
                    <>
                        <InputField
                            required
                            label="Serp API Key"
                            type="password"
                            name="api_key"
                            placeholder={t('build.enterApiKey')}
                            value={currentTool?.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="serp-api-key"
                        />
                        <InputField
                            required
                            label="Search Engine"
                            name="engine"
                            placeholder="google, bing, etc."
                            value={currentTool?.engine || ''}
                            onChange={handleParamChange}
                            error={formErrors.engine}
                            id="serp-engine"
                        />
                    </>
                );
            case 'tavily':
                return (
                    <InputField
                        required
                        label="Tavily API Key"
                        type="password"
                        name="api_key"
                        placeholder={t('build.enterApiKey')}
                        value={currentTool?.api_key || ''}
                        onChange={handleParamChange}
                        error={formErrors.api_key}
                        id="tavily-api-key"
                    />
                );
             return null;
        }
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <SelectField
                label="联网搜索工具选择"
                value={selectedTool}
                onChange={handleToolChange}
                options={[
                    { value: 'bing', label: 'Bing 搜索' },
                    { value: 'bocha', label: '博查websearch' },
                    { value: 'jina', label: 'Jina 深度搜索' },
                    { value: 'serp', label: 'Serp API' },
                    { value: 'tavily', label: 'Tavily' },
                ]}
                id="search-tool-selector"
                name="search_tool"
            />

            <div className="space-y-4">
                <Label className="bisheng-label">联网搜索工具配置</Label>
                {renderParams()}
            </div>

            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('build.cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t('build.confirm')}
                </Button>
            </DialogFooter>
        </form>
    );
};

export default WebSearchForm;