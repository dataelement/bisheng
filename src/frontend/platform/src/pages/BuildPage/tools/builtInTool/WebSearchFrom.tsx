import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField, SelectField } from "./InputField";
import { Label } from '@/components/bs-ui/label';

const defaultToolParams = {
    bing: { api_key: '', base_url: 'https://api.bing.microsoft.com/v7.0/search' },
    bocha: { api_key: '' },
    jina: { api_key: '' },
    serp: { api_key: '', engine: '' },
    tavily: { api_key: '' }
};

const WebSearchForm = ({ config, onSubmit, errors = {} }) => {
    const { t } = useTranslation();
    const [selectedTool, setSelectedTool] = useState(config.tool || 'bing');
    const [localParams, setLocalParams] = useState(() => ({
        ...defaultToolParams[selectedTool],
        ...config.params
    }));
    const [formErrors, setFormErrors] = useState({});

    const handleToolChange = (tool) => {
        setSelectedTool(tool);
        setLocalParams({
            ...defaultToolParams[tool],
            ...config.params
        });
    };

    const handleParamChange = (e) => {
        const { name, value } = e.target;
        setLocalParams(prev => ({ ...prev, [name]: value }));
    };

    const validateForm = () => {
        const errors = {};
        let isValid = true;

        // 通用API Key验证
        if (!localParams.api_key) {
            errors.api_key = t('build.fieldRequired');
            isValid = false;
        }

        // Bing特定验证
        if (selectedTool === 'bing' && !localParams.base_url) {
            errors.base_url = t('build.fieldRequired');
            isValid = false;
        }

        // Serp特定验证
        if (selectedTool === 'serp' && !localParams.engine) {
            errors.engine = t('build.fieldRequired');
            isValid = false;
        }

        setFormErrors(errors);
        return isValid;
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (validateForm()) {
            onSubmit({
                tool: selectedTool,
                params: localParams
            });
        }
    };

    const renderParams = () => {
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
                            value={localParams.api_key}
                            onChange={handleParamChange}
                            error={formErrors.api_key} id={undefined}                        />
                        <InputField
                            required
                            label="Bing Search URL"
                            name="base_url"
                            placeholder={t('build.enterSearchUrl')}
                            value={localParams.base_url}
                            onChange={handleParamChange}
                            error={formErrors.base_url} id={undefined}                        />
                    </>
                );
            case 'bocha':
            case 'jina':
            case 'tavily':
                return (
                    <InputField
                        required
                        label="API Key"
                        type="password"
                        name="api_key"
                        placeholder={t('build.enterApiKey')}
                        value={localParams.api_key}
                        onChange={handleParamChange}
                        error={formErrors.api_key} id={undefined}                    />
                );
            case 'serp':
                return (
                    <>
                        <InputField
                            required
                            label="API Key"
                            type="password"
                            name="api_key"
                            placeholder={t('build.enterApiKey')}
                            value={localParams.api_key}
                            onChange={handleParamChange}
                            error={formErrors.api_key} id={undefined}                        />
                        <InputField
                            required
                            label="Engine"
                            name="engine"
                            placeholder={t('build.enterEngine')}
                            value={localParams.engine}
                            onChange={handleParamChange}
                            error={formErrors.engine} id={undefined}                        />
                    </>
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
                    { value: 'serp', label: 'Serp Api' },
                    { value: 'tavily', label: 'Tavily' }
                ]} id={undefined} name={undefined}            />

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