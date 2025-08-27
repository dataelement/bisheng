import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField, SelectField } from "./InputField";

const temp = {
    provider: 'openai',
    openai_api_key: '',
    azure_api_key: '',
    openai_api_base: 'https://api.openai.com/v1',
    openai_proxy: '',
    azure_deployment: '',
    azure_endpoint: '',
    openai_api_version: ''
}

const Dalle3ToolForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation();

    const [localFormData, setLocalFormData] = useState(() => {
        // 如果formData为空，使用默认值
        if (!formData || Object.keys(formData).length === 0) {
            return { ...temp };
        }
        // 优先检查是否有Azure特定字段
        const hasAzureFields = formData.azure_deployment || formData.azure_endpoint || formData.azure_api_key;
        // 检查是否有OpenAI特定字段（排除默认值）
        const hasOpenAIFields = formData.openai_api_key && formData.openai_api_key !== '';
        
        let provider = 'openai'; // 默认值
        
        if (hasAzureFields) {
            provider = 'azure';
        } else if (hasOpenAIFields) {
            provider = 'openai';
        }
        
        // 根据provider类型设置正确的API Key字段
        return {
            ...temp,
            ...formData,
            provider,
            openai_api_key: provider === 'openai' ? (formData.openai_api_key || formData.azure_api_key || '') : '',
            azure_api_key: provider === 'azure' ? (formData.azure_api_key || formData.openai_api_key || '') : ''
        };
    });
    
    const [errors, setErrors] = useState({});

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleProviderChange = (value) => {
        setLocalFormData((prev) => ({ ...prev, provider: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;
        
        if (localFormData.provider === 'openai' && !localFormData.openai_api_key) {
            formErrors.openai_api_key = true;
            isValid = false;
        } else if (localFormData.provider === 'azure') {
            if (!localFormData.azure_api_key) {
                formErrors.azure_api_key = true;
                isValid = false;
            }
            if (!localFormData.azure_deployment) {
                formErrors.azure_deployment = true;
                isValid = false;
            }
            if (!localFormData.azure_endpoint) {
                formErrors.azure_endpoint = true;
                isValid = false;
            }
            if (!localFormData.openai_api_version) {
                formErrors.openai_api_version = true;
                isValid = false;
            }
        }
        
        setErrors(formErrors);
        return isValid;
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (validateForm()) {
            // 准备提交的数据，根据provider类型设置正确的API Key字段
            const submitData = { ...localFormData };
            
            if (submitData.provider === 'openai') {
                // 清理Azure相关字段
                submitData.azure_api_key = '';
                submitData.azure_deployment = '';
                submitData.azure_endpoint = '';
                submitData.openai_api_version = '';
            } else {
                // 清理OpenAI相关字段
                submitData.openai_api_key = '';
                submitData.openai_proxy = '';
            }
            
            // 移除临时使用的provider字段（如果需要）
            const { provider, ...finalData } = submitData;
            onSubmit(finalData);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <RadioGroup value={localFormData.provider} className="flex gap-6 mt-2" onValueChange={handleProviderChange}>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="openai" id="provider-openai" />
                    <Label htmlFor="provider-openai">OpenAI</Label>
                </div>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="azure" id="provider-azure" />
                    <Label htmlFor="provider-azure">Azure</Label>
                </div>
            </RadioGroup>

            <div className="flex flex-col gap-4">
                {localFormData.provider === 'openai' ? (
                    <>
                        <InputField
                            required
                            label="OpenAI API Key"
                            type="password"
                            id="openai_api_key"
                            name="openai_api_key"
                            placeholder={t('build.enterApiKey')}
                            value={localFormData.openai_api_key}
                            onChange={handleChange}
                            error={errors.openai_api_key}
                        />
                        <InputField
                            label="OpenAI Base URL"
                            id="openai_api_base"
                            name="openai_api_base"
                            placeholder={t('build.enterBaseUrl')}
                            value={localFormData.openai_api_base}
                            onChange={handleChange}
                        />
                        <InputField
                            label="OpenAI Proxy"
                            id="openai_proxy"
                            name="openai_proxy"
                            placeholder={t('build.enterProxy')}
                            value={localFormData.openai_proxy}
                            onChange={handleChange}
                        />
                    </>
                ) : (
                    <>
                        <InputField
                            required
                            label="Azure OpenAI API Key"
                            type="password"
                            id="azure_api_key"
                            name="azure_api_key"
                            placeholder={t('build.enterApiKey')}
                            value={localFormData.azure_api_key}
                            onChange={handleChange}
                            error={errors.azure_api_key}
                        />
                        <InputField
                            required
                            label="Deployment Name"
                            id="azure_deployment"
                            name="azure_deployment"
                            placeholder={t('build.enterDeploymentName')}
                            value={localFormData.azure_deployment}
                            onChange={handleChange}
                            error={errors.azure_deployment}
                        />
                        <InputField
                            required
                            label="Azure Endpoint"
                            id="azure_endpoint"
                            name="azure_endpoint"
                            placeholder="格式示例：https://xxx.openai.azure.com/"
                            value={localFormData.azure_endpoint}
                            onChange={handleChange}
                            error={errors.azure_endpoint}
                        />
                        <InputField
                            required
                            label="Openai API Version"
                            id="openai_api_version"
                            name="openai_api_version"
                            placeholder="格式示例：2024-02-01"
                            value={localFormData.openai_api_version}
                            onChange={handleChange}
                            error={errors.openai_api_version}
                        />
                    </>
                )}
            </div>

            {/* 这里是 DialogFooter */}
            <DialogFooter className="mt-4">
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

export default Dalle3ToolForm;