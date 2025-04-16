import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import {InputField, SelectField} from "./InputField";

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
        const newFormData = { ...temp, ...formData };
        newFormData.provider = formData.azure_deployment ? 'azure' : 'openai';
        const apiKey = formData.openai_api_key;
        if (formData.provider === 'openai') {
            newFormData.openai_api_key = apiKey;
            newFormData.azure_api_key = '';
        } else {
            newFormData.openai_api_key = '';
            newFormData.azure_api_key = apiKey;
        }
        return newFormData
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
            } else if (!localFormData.azure_deployment) {
                formErrors.azure_deployment = true;
                isValid = false;
            } else if (!localFormData.azure_endpoint) {
                formErrors.azure_endpoint = true;
                isValid = false;
            } else if (!localFormData.openai_api_version) {
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
            // 整理数据 sumbit
            const fields: any = {};
            if (localFormData.provider === 'openai') {
                fields.openai_api_key = localFormData.openai_api_key;
                fields.openai_api_base = localFormData.openai_api_base;
                fields.openai_proxy = localFormData.openai_proxy;
            } else {
                fields.openai_api_key = localFormData.azure_api_key;
                fields.azure_deployment = localFormData.azure_deployment;
                fields.azure_endpoint = localFormData.azure_endpoint;
                fields.openai_api_version = localFormData.openai_api_version;
                fields.openai_api_type = 'azure';
            }
            onSubmit(fields);
        }
    };

    return (
        <>
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
                        id="azure_api_key" // 修改为 azure_api_key
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

            {/* 这里是 DialogFooter */}
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('build.cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" onClick={handleSubmit}>
                    {t('build.confirm')}
                </Button>
            </DialogFooter>
        </>
    );
};

export default Dalle3ToolForm;
