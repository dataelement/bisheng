import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState, useEffect, useRef } from 'react';
import { useTranslation } from "react-i18next";
import { InputField, SelectField } from "./InputField";
import { Label } from '@/components/bs-ui/label';
import { useWebSearchStore } from '../webSearchStore'
import { toast, useToast } from '@/components/bs-ui/toast/use-toast';
const defaultToolParams = {
    bing: {
        type: 'bing',
        config: {
            api_key: '',
            base_url: 'https://api.bing.microsoft.com/v7.0/search'
        }
    },
    bocha: {
        type: 'bocha',
        config: {
            api_key: ''
        }
    },
    jina: {
        type: 'jina',
        config: {
            api_key: ''
        }
    },
    serp: {
        type: 'serp',
        config: {
            api_key: '',
            engine: ''
        }
    },
    tavily: {
        type: 'tavily',
        config: {
            api_key: ''
        }
    }
};

const WebSearchForm = ({ formData, onSubmit, errors = {} }) => {
    const { t } = useTranslation();
    const { toast } = useToast();
    const { config: webSearchData, setConfig } = useWebSearchStore();
    
    // 初始化所有工具配置
    const [allToolsConfig, setAllToolsConfig] = useState(() => ({
        bing: {
            type: 'bing',
            config: { 
                ...defaultToolParams.bing.config,
                ...(webSearchData?.bing?.config || {})
            }
        },
        bocha: {
            type: 'bocha',
            config: { 
                ...defaultToolParams.bocha.config,
                ...(webSearchData?.bocha?.config || {})
            }
        },
        jina: {
            type: 'jina',
            config: { 
                ...defaultToolParams.jina.config,
                ...(webSearchData?.jina?.config || {})
            }
        },
        serp: {
            type: 'serp',
            config: { 
                ...defaultToolParams.serp.config,
                ...(webSearchData?.serp?.config || {})
            }
        },
        tavily: {
            type: 'tavily',
            config: { 
                ...defaultToolParams.tavily.config,
                ...(webSearchData?.tavily?.config || {})
            }
        }
    }));

    const [selectedTool, setSelectedTool] = useState(webSearchData?.tool || 'bing');
    const [formErrors, setFormErrors] = useState({});

    const handleToolChange = (tool) => {
        setSelectedTool(tool);
    };

    const handleParamChange = (e) => {
        const { name, value } = e.target;
        setAllToolsConfig(prev => ({
            ...prev,
            [selectedTool]: {
                ...prev[selectedTool],
                config: {
                    ...prev[selectedTool].config,
                    [name]: value
                }
            }
        }));
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        const newConfig = {
            ...webSearchData,
            tool: selectedTool,
            [selectedTool]: allToolsConfig[selectedTool],
            ...Object.keys(allToolsConfig).reduce((acc, tool) => {
                if (tool !== selectedTool) {
                    acc[tool] = allToolsConfig[tool];
                }
                return acc;
            }, {})
        };

        try {
            setConfig(newConfig);
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

        const { config } = currentTool;

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
                            value={config?.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="bing-api-key"
                        />
                        <InputField
                            required
                            label="Bing Search URL"
                            name="base_url"
                            placeholder={t('build.enterSearchUrl')}
                            value={config?.base_url || defaultToolParams.bing.config.base_url}
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
                        value={config?.api_key || ''}
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
                        value={config?.api_key || ''}
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
                            value={config?.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="serp-api-key"
                        />
                        <InputField
                            required
                            label="Search Engine"
                            name="engine"
                            placeholder="google, bing, etc."
                            value={config?.engine || ''}
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
                        value={config?.api_key || ''}
                        onChange={handleParamChange}
                        error={formErrors.api_key}
                        id="tavily-api-key"
                    />
                );
            default:
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
                    { value: 'tavily', label: 'Tavily' }
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