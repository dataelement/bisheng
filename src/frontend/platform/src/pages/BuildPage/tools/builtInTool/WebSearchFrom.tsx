import { useEffect, useState } from 'react';
import { useTranslation } from "react-i18next";
import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from '@/components/bs-ui/label';
import { toast } from '@/components/bs-ui/toast/use-toast';
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import { useWebSearchStore } from '../webSearchStore';
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
        api_key: ''
    },
    searXNG: {
        server_url: ''
    },
};

const WebSearchForm = ({ formData, onSubmit, errors = {},enabled,prompt }) => {
    const { t } = useTranslation();
    const { config: webSearchData, setConfig } = useWebSearchStore();
    const [loading, setLoading] = useState(true);

    const [allToolsConfig, setAllToolsConfig] = useState(() => {
        const mergedConfig = {
            ...defaultToolParams,
            ...(webSearchData?.config || {}),
            ...(formData?.config || {})
        };
        return mergedConfig;
    });

    const [selectedTool, setSelectedTool] = useState(webSearchData?.type || 'bing');
    const [formErrors, setFormErrors] = useState({});

    // 初始化时获取联网搜索配置
    // useEffect(() => {
    //     const fetchWebSearchConfig = async () => {
    //         try {
    //             const res = await getAssistantToolsApi('default');
    //             const webSearchTool = res.find(item => item.name === "联网搜索");

    //             if (webSearchTool && webSearchTool.extra) {
    //                 const extraData = JSON.parse(webSearchTool.extra);
    //                 setSelectedTool(extraData.type || 'bing');
    //                 setAllToolsConfig({
    //                     ...defaultToolParams,
    //                     ...extraData.config
    //                 });
    //             }
    //         } catch (error) {
    //             toast({
    //                 title: "获取配置失败",
    //                 description: error.message,
    //                 variant: "error",
    //             });
    //         } finally {
    //             setLoading(false);
    //         }
    //     };

    //     fetchWebSearchConfig();
    // }, []);

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
            api_key: (value) => !value && 'API Key 不能为空'
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

    const handleSubmit = (e) => {
        e.preventDefault();
        const errors = {};
        const currentToolRules = validationRules[selectedTool];

        Object.keys(currentToolRules).forEach(key => {
            const error = currentToolRules[key](allToolsConfig[selectedTool][key]);
            if (error) {
                errors[key] = error;
            }
        });

        if (Object.keys(errors).length > 0) {
            setFormErrors(errors);
            return;
        }

        const newConfig = {
            enabled,
            type: selectedTool,
            config: allToolsConfig,
            prompt
        };
        try {
            setConfig(newConfig);
            console.log('提交的数据:', newConfig);
            console.log("webSearchData 是否更新?", webSearchData);
            toast({
                title: t('skills.saveSuccessful'),
                variant: "success",
            });
            onSubmit?.(newConfig);
        } catch (error) {
            toast({
                title: t('failed'),
                description: error.message,
                variant: "error",
            });
        }
    };

    const renderParams = () => {
      

        const currentTool = allToolsConfig[selectedTool];
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
                            value={currentTool.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="bing-api-key"
                        />
                        <InputField
                            required
                            label="Bing Search URL"
                            name="base_url"
                            value={currentTool.base_url || defaultToolParams.bing.base_url}
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
                        label="API Key"
                        type="password"
                        name="api_key"
                        value={currentTool.api_key || ''}
                        onChange={handleParamChange}
                        error={formErrors.api_key}
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
                        value={currentTool.api_key || ''}
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
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentTool.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="serp-api-key"
                        />
                        <InputField
                            required
                            label="engine"
                            name="engine"
                            value={currentTool.engine || 'baidu'}
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
                        label="API Key"
                        type="password"
                        name="api_key"
                        value={currentTool.api_key || ''}
                        onChange={handleParamChange}
                        error={formErrors.api_key}
                        id="tavily-api-key"
                    />
                );
            case 'cloudsway':
                    return (
                        <InputField
                            required
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentTool.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="cloudsway-api-key"
                        />
                    );
            case 'searXNG':
                return (
                    <InputField
                        required
                        label={t('chatConfig.webSearch.serverUrl')}
                        name="server_url"
                        value={currentTool.server_url || ''}
                        onChange={handleParamChange}
                        error={formErrors.server_url}
                        id="searxng-server-url"
                        placeholder={t('chatConfig.webSearch.serverUrlPlaceholder')}
                    />
                );
            default:
                return null;
        }
    };

    return (
        <>
           {/* {loading? <LoadingIcon />: */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
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
                <Button className="px-11" type="submit">
                    {t('build.confirm')}
                </Button>
            </DialogFooter>
        </form>
        </>
    
    );
};

export default WebSearchForm;