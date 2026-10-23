// @ts-strict-ignore
import { Button } from '@bisheng/ui';

import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { PassInput } from '@/components/bs-comp/formFields/PassInput';
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, Radio as RadioGroupItem } from "@bisheng/ui";
import { getSandboxConfApi, saveSandboxConfApi, testSandboxConfApi } from "@/controllers/API/tools";
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from "react-i18next";
import { AppHint } from "../../components/AppHint";
import { InputField } from "./InputField";
import { SandboxEndpointFields, type SandboxProbeResult } from "./SandboxEndpointFields";
import { parseSandboxEndpoints, sandboxSavePlan } from "./sandboxEndpoint";

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
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [probeResults, setProbeResults] = useState<SandboxProbeResult[]>([]);
    const loadedSandbox = useRef({ addressText: '', token: '' });
    const [sandbox, setSandbox] = useState({
        addressText: '',
        token: '',
        addressSource: 'default',
        tokenSource: 'default',
        deploymentAddress: '',
    });

    useEffect(() => {
        let cancelled = false;
        getSandboxConfApi()
            .then((data) => {
                if (cancelled || !data) return;
                const addressText = Array.isArray(data.endpoints) ? data.endpoints.join('\n') : '';
                const token = data.token || '';
                loadedSandbox.current = { addressText, token };
                setSandbox({
                    addressText,
                    token,
                    addressSource: data.address_source || 'default',
                    tokenSource: data.token_source || 'default',
                    deploymentAddress: data.deployment_address || '',
                });
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, []);

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

    const handleTestConnection = async () => {
        setTesting(true);
        try {
            const data = await testSandboxConfApi({
                endpoints: parseSandboxEndpoints(sandbox.addressText),
                token: sandbox.token,
            });
            setProbeResults(Array.isArray(data?.results) ? data.results : []);
        } catch {
            setProbeResults([]);
        } finally {
            setTesting(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!validateForm()) return;
        const submitData = {
            type: localFormData.executionMode,
            config: {
                e2b: {
                    type: localFormData.serviceProvider,
                    ...(localFormData.serviceProvider === 'private' && {
                        domain: localFormData.privateDomain,
                        api_key: localFormData.privateApiKey
                    }),
                    ...(localFormData.serviceProvider === 'official' && {
                        api_key: localFormData.officialApiKey
                    })
                },
                private: {
                    domain: localFormData.privateDomain,
                    api_key: localFormData.privateApiKey
                },
                official: {
                    api_key: localFormData.officialApiKey
                },
                // Pool URL / token stay in system config, never extra.
                container: {}
            }
        };
        const changed = sandbox.addressText !== loadedSandbox.current.addressText
            || sandbox.token !== loadedSandbox.current.token;
        if (sandboxSavePlan(localFormData.executionMode, changed) === 'sandbox-then-tool') {
            setSaving(true);
            try {
                await saveSandboxConfApi({
                    endpoints: parseSandboxEndpoints(sandbox.addressText),
                    token: sandbox.token,
                });
            } catch {
                return;
            } finally {
                setSaving(false);
            }
        }
        onSubmit(submitData);
    };

    return (
        <>
            <div className="mb-6">
                <Label className=" mb-3 mt-4 block">
                    {t('executionModeLabel')}
                </Label>
                <RadioGroup
                    value={localFormData.executionMode}
                    className="flex flex-wrap gap-6"
                    onValueChange={handleExecutionModeChange}
                >
                    <div className="flex items-center space-x-2">
                        <RadioGroupItem value="local" id="execution-local" />
                        <Label htmlFor="execution-local">
                            {t('executionLocalLabel')}
                        </Label>
                    </div>
                    <div className="flex items-center space-x-2">
                        <RadioGroupItem value="container" id="execution-container" />
                        <Label htmlFor="execution-container">
                            {t('executionContainerLabel')}{' '}
                            <AppHint content={t('executionContainerHint')} />
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

            {localFormData.executionMode === 'container' && (
                <SandboxEndpointFields
                    addressText={sandbox.addressText}
                    token={sandbox.token}
                    addressSource={sandbox.addressSource}
                    tokenSource={sandbox.tokenSource}
                    deploymentAddress={sandbox.deploymentAddress}
                    testing={testing}
                    results={probeResults}
                    onAddressChange={(value) => setSandbox((prev) => ({ ...prev, addressText: value }))}
                    onTokenChange={(value) => setSandbox((prev) => ({ ...prev, token: value }))}
                    onTest={handleTestConnection}
                />
            )}

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
                                    <AppHint content={t('providerPrivateTooltip')} />
                                </Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="official" id="provider-official" />
                                <Label htmlFor="provider-official">
                                    {t('providerOfficialLabel')}{' '}
                                    <AppHint content={t('providerOfficialTooltip')} />
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
                    <Button variant="outlined" type="button" color="default">
                        {t('cancel', { ns: 'bs' })}
                    </Button>
                </DialogClose>
                <Button disabled={saving} onClick={handleSubmit}>
                    {t('save', { ns: 'bs' })}
                </Button>
            </DialogFooter>
        </>
    );
};

export default Dalle3ToolForm;
