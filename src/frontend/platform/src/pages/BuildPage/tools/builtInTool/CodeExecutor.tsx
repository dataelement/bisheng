import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { PassInput } from '@/components/bs-ui/input';
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { QuestionTooltip } from '@/components/bs-ui/tooltip';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

const Dalle3ToolForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation('tool');
    const domainRef = useRef(null);
    const apiKeyRef = useRef(null);

    const [localFormData, setLocalFormData] = useState(() => {
        // Extract all configurations from form data
        const executionMode = formData.type || 'local';
        const serviceProvider = formData.config?.e2b?.type || 'private';

        // Get both configurations at the same time
        const privateDomain = formData.config?.private?.domain || formData.config?.e2b_private?.domain || '';
        const privateApiKey = formData.config?.private?.api_key || formData.config?.e2b_private?.api_key || '';
        const officialApiKey = formData.config?.official?.api_key || formData.config?.e2b_official?.api_key || '';

        return {
            executionMode,
            serviceProvider,
            privateDomain,
            privateApiKey,
            officialApiKey
        };
    });

    const [errors, setErrors] = useState({});

    useEffect(() => {
        if (domainRef.current) {
            domainRef.current.value = '';
        }
        if (apiKeyRef.current) {
            apiKeyRef.current.value = '';
        }
    }, []);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleExecutionModeChange = (value) => {
        setLocalFormData((prev) => ({ ...prev, executionMode: value }));
    };

    const handleServiceProviderChange = (value) => {
        setLocalFormData((prev) => ({ ...prev, serviceProvider: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;

        if (localFormData.executionMode === 'e2b') {
            // Validate configuration of the currently selected service provider
            if (localFormData.serviceProvider === 'private') {
                if (!localFormData.privateDomain) {
                    formErrors.privateDomain = t('domainCannotBeEmpty');
                    isValid = false;
                }
                if (!localFormData.privateApiKey) {
                    formErrors.privateApiKey = t('apiKeyCannotBeEmpty');
                    isValid = false;
                }
            } else {
                if (!localFormData.officialApiKey) {
                    formErrors.officialApiKey = t('apiKeyCannotBeEmpty');
                    isValid = false;
                }
            }
        }
        setErrors(formErrors);
        return isValid;
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (validateForm()) {
            // Build complete form data and save both configurations
            const submitData = {
                type: localFormData.executionMode,
                config: {
                    e2b: {
                        type: localFormData.serviceProvider,
                        // Save configuration according to the selected service provider
                        ...(localFormData.serviceProvider === 'private' && {
                            domain: localFormData.privateDomain,
                            api_key: localFormData.privateApiKey
                        }),
                        ...(localFormData.serviceProvider === 'official' && {
                            api_key: localFormData.officialApiKey
                        })
                    },
                    // Save both configurations
                    private: {
                        domain: localFormData.privateDomain,
                        api_key: localFormData.privateApiKey
                    },
                    official: {
                        api_key: localFormData.officialApiKey
                    }
                }
            };

            onSubmit(submitData);
        }
    };

    return (
        <>
            <div className="mb-6">
                <Label className=" mb-3 mt-4 block">
                    {t('executionModeLabel')}
                </Label>
                <RadioGroup
                    value={localFormData.executionMode}
                    className="flex gap-6"
                    onValueChange={handleExecutionModeChange}
                >
                    <div className="flex items-center space-x-2">
                        <RadioGroupItem value="local" id="execution-local" />
                        <Label htmlFor="execution-local">
                            {t('executionLocalLabel')}
                        </Label>
                    </div>
                    <div className="flex items-center space-x-2">
                        <RadioGroupItem value="e2b" id="execution-e2b" />
                        <Label htmlFor="execution-e2b">
                            {t('executionE2bLabel')}
                        </Label>
                    </div>
                </RadioGroup>
            </div>

            {/* Show configuration only when E2B sandbox execution is selected */}
            {localFormData.executionMode === 'e2b' && (
                <div className="space-y-4">
                    <div>
                        <Label className="mb-3 block">
                            {t('serviceProviderLabel')}
                        </Label>
                        <RadioGroup
                            value={localFormData.serviceProvider}
                            className="flex gap-6"
                            onValueChange={handleServiceProviderChange}
                        >
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="private" id="provider-private" />
                                <Label htmlFor="provider-private">
                                    {t('providerPrivateLabel')}{' '}
                                    <QuestionTooltip content={t('providerPrivateTooltip')} />
                                </Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="official" id="provider-official" />
                                <Label htmlFor="provider-official">
                                    {t('providerOfficialLabel')}{' '}
                                    <QuestionTooltip content={t('providerOfficialTooltip')} />
                                </Label>
                            </div>
                        </RadioGroup>
                    </div>

                    {localFormData.serviceProvider === 'private' && (
                        <InputField
                            required
                            label={<Label>Domain</Label>}
                            id="e2b-domain-input"
                            name="privateDomain"
                            placeholder="https://e2b.internal.mycorp"
                            value={localFormData.privateDomain}
                            onChange={handleChange}
                            error={errors.privateDomain}
                        />
                    )}

                    <PassInput
                        required
                        id="e2b-apikey-input"
                        label={<Label>API Key</Label>}
                        placeholder={t('enterApiKeyPlaceholder')}
                        type='text'
                        name={localFormData.serviceProvider === 'private' ? 'privateApiKey' : 'officialApiKey'}
                        onChange={handleChange}
                        value={localFormData.serviceProvider === 'private' ? localFormData.privateApiKey : localFormData.officialApiKey}
                        error={localFormData.serviceProvider === 'private' ? errors.privateApiKey : errors.officialApiKey}
                    />
                </div>
            )}

            <DialogFooter className="mt-6">
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('cancel', { ns: 'bs' })}
                    </Button>
                </DialogClose>
                <Button className="px-11" onClick={handleSubmit}>
                    {t('save', { ns: 'bs' })}
                </Button>
            </DialogFooter>
        </>
    );
};

export default Dalle3ToolForm;
