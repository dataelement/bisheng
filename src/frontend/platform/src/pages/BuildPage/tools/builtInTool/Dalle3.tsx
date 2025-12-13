import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

const temp = {
    provider: 'openai',
    openai_api_key: '',
    openai_api_base: 'https://api.openai.com/v1',
    openai_proxy: '',
    azure_deployment: '',
    azure_endpoint: '',
    openai_api_version: ''
}

const Dalle3ToolForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation('tool');
    const [pro, setPro] = useState('');
    const [localFormData, setLocalFormData] = useState(() => {
        if (!formData || Object.keys(formData).length === 0) {
            return { ...temp };
        }

        // Determine which configuration to use based on existing fields
        const hasAzureFields = formData.azure_deployment || formData.azure_endpoint || formData.openai_api_version;
        const provider = hasAzureFields ? 'azure' : 'openai';

        // Decide which API key to display based on provider type
        let displayApiKey = '';
        setPro(provider);

        if (provider === 'openai') {
            displayApiKey = formData.openai_api_key || '';
            formData.openai_api_key = displayApiKey;
        } else {
            displayApiKey = formData.openai_api_key || '';
            formData.openai_api_key = displayApiKey;
        }

        return {
            ...temp,
            ...formData,
            provider,
            openai_api_key: displayApiKey
        };
    });

    const [errors, setErrors] = useState({});

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleProviderChange = (value) => {
        console.log(value, pro, formData.openai_api_key);

        if (value !== pro) {
            localFormData.openai_api_key = '';
        } else {
            localFormData.openai_api_key = formData.openai_api_key;
        }
        setLocalFormData((prev) => ({ ...prev, provider: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;

        if (!localFormData.openai_api_key) {
            formErrors.openai_api_key = true;
            isValid = false;
        }

        if (localFormData.provider === 'azure') {
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
            // Create submission data based on the currently selected provider
            let finalData = {};

            if (localFormData.provider === 'openai') {
                // Only save OpenAI-related fields
                finalData = {
                    openai_api_key: localFormData.openai_api_key,
                    openai_api_base: localFormData.openai_api_base,
                    openai_proxy: localFormData.openai_proxy
                };
            } else {
                // Only save Azure-related fields
                finalData = {
                    openai_api_key: localFormData.openai_api_key,
                    azure_deployment: localFormData.azure_deployment,
                    azure_endpoint: localFormData.azure_endpoint,
                    openai_api_version: localFormData.openai_api_version
                };
            }

            onSubmit(finalData);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <RadioGroup
                value={localFormData.provider}
                className="flex gap-6 mt-2"
                onValueChange={handleProviderChange}
            >
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
                {/* Unified API Key field */}
                <InputField
                    required
                    label={localFormData.provider === 'openai' ? "OpenAI API Key" : "Azure OpenAI API Key"}
                    type="password"
                    id="openai_api_key"
                    name="openai_api_key"
                    placeholder={t('build.enterApiKey')}
                    value={localFormData.openai_api_key}
                    onChange={handleChange}
                    error={errors.openai_api_key}
                />

                {localFormData.provider === 'openai' ? (
                    <>
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
                            placeholder={t('azureEndpointPlaceholder')}
                            value={localFormData.azure_endpoint}
                            onChange={handleChange}
                            error={errors.azure_endpoint}
                        />
                        <InputField
                            required
                            label="OpenAI API Version"
                            id="openai_api_version"
                            name="openai_api_version"
                            placeholder={t('openaiApiVersionPlaceholder')}
                            value={localFormData.openai_api_version}
                            onChange={handleChange}
                            error={errors.openai_api_version}
                        />
                    </>
                )}
            </div>

            <DialogFooter className="mt-4">
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('cancel', { ns: 'bs' })}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t('confirm', { ns: 'bs' })}
                </Button>
            </DialogFooter>
        </form>
    );
};

export default Dalle3ToolForm;
