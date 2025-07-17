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
        engine: 'baidu'
    },
    tavily: {
        api_key: ''
    },
};

const WebSearchForm = ({ formData, onSubmit, errors = {} }) => {
    const { t } = useTranslation();
    const { toast } = useToast();
    const { config: webSearchData, setConfig } = useWebSearchStore();
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
            engine: (value) => !value && 'Search Engine 不能为空'
        },
        tavily: {
            api_key: (value) => !value && 'API Key 不能为空'
        }
        };
    const [allToolsConfig, setAllToolsConfig] = useState(() => {
        return webSearchData?.config || {
            bing: defaultToolParams.bing,
            bocha: defaultToolParams.bocha,
            jina: defaultToolParams.jina,
            serp: defaultToolParams.serp,
            tavily: defaultToolParams.tavily
        };
    });

    const [selectedTool, setSelectedTool] = useState(webSearchData?.type || 'bing');
    const [formErrors, setFormErrors] = useState({});

 const handleToolChange = (tool) => {
    setSelectedTool(tool);
    setFormErrors({});
};
    useEffect(() => {
        if (webSearchData) {
            setAllToolsConfig(webSearchData.config || {
                bing: defaultToolParams.bing,
                bocha: defaultToolParams.bocha,
                jina: defaultToolParams.jina,
                serp: defaultToolParams.serp,
                tavily: defaultToolParams.tavily
            });
            setSelectedTool(webSearchData.type || 'bing');
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
    
    // 清除当前字段的错误
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
            type: selectedTool,
            config: {
            bing: allToolsConfig.bing,
            bocha: allToolsConfig.bocha,
            jina: allToolsConfig.jina,
            serp: allToolsConfig.serp,
            tavily: allToolsConfig.tavily
        }
        };
        try {
            setConfig(newConfig);
            console.log('提交的数据:', newConfig);
console.log("webSearchData 是否更新?", webSearchData);
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
        console.log(currentTool,111);
        
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
                            value={currentTool?.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="bing-api-key"
                        />
                        <InputField
                            required
                            label="Bing Search URL"
                            name="base_url"
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
                        label="API Key"
                        type="password"
                        name="api_key"
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
                        label="API Key"
                        type="password"
                        name="api_key"
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
                            label="API Key"
                            type="password"
                            name="api_key"
                            value={currentTool?.api_key || ''}
                            onChange={handleParamChange}
                            error={formErrors.api_key}
                            id="serp-api-key"
                        />
                        <InputField
                            required
                            label="Search Engine"
                            name="engine"
                            value={currentTool?.engine || 'baidu'}
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
                label="联网搜索引擎"
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