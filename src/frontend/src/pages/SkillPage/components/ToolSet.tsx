import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { updateAssistantToolApi } from "@/controllers/API/assistant";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { forwardRef, useImperativeHandle, useState } from "react";
import { useTranslation } from "react-i18next";

const InputField = ({ label, type = "text", id, name, required = false, placeholder, value, onChange, error = '' }) => (
    <div key={id} className="">
        <label htmlFor={id} className="bisheng-label">{label}{required && <span className="bisheng-tip">*</span>}</label>
        <Input type={type} id={id} name={name} placeholder={placeholder} className="mt-2" value={value} onChange={onChange} />
        {error && <p className="bisheng-tip mt-1">{label} 不能为空</p>}
    </div>
);

const validateField = (name, value, t) => {
    if (!value) return name + '不能为空';
    return '';
};

const ToolSet = forwardRef(function ToolSet({ onChange }, ref) {
    const [open, setOpen] = useState(false);
    const { t } = useTranslation();
    const [formData, setFormData] = useState({
        provider: 'openai',
        openai_api_key: '',
        azure_api_key: '', // 新增 azure 的 API key
        openai_api_base: 'https://api.openai.com/v1',
        openai_proxy: '',
        bing_subscription_key: '',
        bing_search_url: 'https://api.bing.microsoft.com/v7.0/search',
        azure_deployment: '',
        azure_endpoint: '',
        openai_api_version: ''
    });

    const [id, setId] = useState('');
    const [name, setName] = useState('');
    const [errors, setErrors] = useState({});

    useImperativeHandle(ref, () => ({
        edit: (item) => {
            setName(item.name);
            setId(item.id);

            const configStr = item.children[0]?.extra;
            if (configStr) {
                const config = JSON.parse(configStr);
                config.provider = config.azure_deployment ? 'azure' : 'openai';
                const apiKey = config.openai_api_key
                if (config.provider === 'openai') {
                    config.openai_api_key = apiKey;
                    config.azure_api_key = ''
                } else {
                    config.openai_api_key = '';
                    config.azure_api_key = apiKey;
                }
                setFormData(config);
            } else {
                resetFormData();
            }
            setOpen(true);
        }
    }));

    const resetFormData = () => {
        setFormData({
            provider: 'openai',
            openai_api_key: '',
            azure_api_key: '', // 重置 azure 的 API key
            openai_api_base: 'https://api.openai.com/v1',
            openai_proxy: '',
            bing_subscription_key: '',
            bing_search_url: 'https://api.bing.microsoft.com/v7.0/search',
            azure_deployment: '',
            azure_endpoint: '',
            openai_api_version: ''
        });
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        const error = validateField(name, value, t);

        setFormData(prev => ({ ...prev, [name]: value }));
        setErrors(prev => ({ ...prev, [name]: error }));
    };

    const handleProviderChange = (value) => {
        setFormData(prev => ({ ...prev, provider: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;

        const fieldsToValidate = getFieldsToValidate();
        fieldsToValidate.forEach((key) => {
            const error = validateField(key, formData[key], t);
            if (error) {
                formErrors[key] = error;
                isValid = false;
            }
        });

        setErrors(formErrors);
        return [isValid, formErrors];
    };

    const getFieldsToValidate = () => {
        const fields = [];
        if (name === 'Dalle3绘画') {
            fields.push(formData.provider === 'openai' ? 'openai_api_key' : 'azure_api_key'); // 根据 provider 决定校验哪个 API key
            if (formData.provider !== 'openai') {
                fields.push('azure_deployment', 'azure_endpoint', 'openai_api_version');
            }
        } else if (name === 'Bing web搜索') {
            fields.push('bing_subscription_key', 'bing_search_url');
        } else if (name === '天眼查') {
            fields.push('api_key');
        }
        return fields;
    };

    const { message, toast } = useToast();

    const handleSubmit = async (e) => {
        e.preventDefault();
        const [isValid, formErrors] = validateForm();
        if (!isValid) return

        const fieldsToSubmit = getFieldsToSubmit();
        await captureAndAlertRequestErrorHoc(updateAssistantToolApi(id, fieldsToSubmit));
        setOpen(false);
        message({ variant: 'success', description: t('build.saveSuccess') });
        onChange();
    };

    const getFieldsToSubmit = () => {
        const fields: any = {};
        if (name === 'Dalle3绘画') {
            // 提交时根据 provider 提交不同的 API key
            if (formData.provider === 'openai') {
                fields.openai_api_key = formData.openai_api_key;
                fields.openai_api_base = formData.openai_api_base;
                fields.openai_proxy = formData.openai_proxy;
            } else {
                fields.openai_api_key = formData.azure_api_key; // 提交 azure 的 API key
                fields.azure_deployment = formData.azure_deployment;
                fields.azure_endpoint = formData.azure_endpoint;
                fields.openai_api_version = formData.openai_api_version;
                fields.openai_api_type = 'azure';
            }
        } else if (name === 'Bing web搜索') {
            fields.bing_subscription_key = formData.bing_subscription_key;
            fields.bing_search_url = formData.bing_search_url;
        } else if (name === '天眼查') {
            fields.api_key = formData.api_key;
        }
        return fields;
    };

    const renderFormContent = () => {
        switch (name) {
            case 'Dalle3绘画':
                return (
                    <>
                        <RadioGroup value={formData.provider} className="flex gap-6 mt-2" onValueChange={handleProviderChange}>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="openai" id="provider-openai" />
                                <Label htmlFor="provider-openai">OpenAI</Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="azure" id="provider-azure" />
                                <Label htmlFor="provider-azure">Azure</Label>
                            </div>
                        </RadioGroup>
                        {formData.provider === 'openai' ? (
                            <>
                                <InputField
                                    required
                                    label="OpenAI API Key"
                                    type="password"
                                    id="openai_api_key"
                                    name="openai_api_key"
                                    placeholder={t('build.enterApiKey')}
                                    value={formData.openai_api_key}
                                    onChange={handleChange}
                                    error={errors.openai_api_key}
                                />
                                <InputField
                                    label="OpenAI Base URL"
                                    id="openai_api_base"
                                    name="openai_api_base"
                                    placeholder={t('build.enterBaseUrl')}
                                    value={formData.openai_api_base}
                                    onChange={handleChange}
                                />
                                <InputField
                                    label="OpenAI Proxy"
                                    id="openai_proxy"
                                    name="openai_proxy"
                                    placeholder={t('build.enterProxy')}
                                    value={formData.openai_proxy}
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
                                    value={formData.azure_api_key}
                                    onChange={handleChange}
                                    error={errors.azure_api_key}
                                />
                                <InputField
                                    required
                                    label="Deployment Name"
                                    id="azure_deployment"
                                    name="azure_deployment"
                                    placeholder={t('build.enterDeploymentName')}
                                    value={formData.azure_deployment}
                                    onChange={handleChange}
                                    error={errors.azure_deployment}
                                />
                                <InputField
                                    required
                                    label="Azure Endpoint"
                                    id="azure_endpoint"
                                    name="azure_endpoint"
                                    placeholder="格式示例：https://xxx.openai.azure.com/"
                                    value={formData.azure_endpoint}
                                    onChange={handleChange}
                                    error={errors.azure_endpoint}
                                />
                                <InputField
                                    required
                                    label="Openai API Version"
                                    id="openai_api_version"
                                    name="openai_api_version"
                                    placeholder="格式示例：2024-02-01"
                                    value={formData.openai_api_version}
                                    onChange={handleChange}
                                    error={errors.openai_api_version}
                                />
                            </>
                        )}
                    </>
                );
            case 'Bing web搜索':
                return (
                    <>
                        <InputField
                            required
                            label="Bing Subscription Key"
                            type="password"
                            id="bing_subscription_key"
                            name="bing_subscription_key"
                            placeholder={t('build.enterSubscriptionKey')}
                            value={formData.bing_subscription_key}
                            onChange={handleChange}
                            error={errors.bing_subscription_key}
                        />
                        <InputField
                            required
                            label="Bing Search URL"
                            id="bing_search_url"
                            name="bing_search_url"
                            placeholder={t('build.enterSearchUrl')}
                            value={formData.bing_search_url}
                            onChange={handleChange}
                            error={errors.bing_search_url}
                        />
                    </>
                );
            case '天眼查':
                return (
                    <InputField
                        required
                        label="API Key"
                        type="password"
                        id="api_key"
                        name="api_key"
                        placeholder={t('build.enterApiKey')}
                        value={formData.api_key}
                        onChange={handleChange}
                        error={errors.api_key}
                    />
                );
            default:
                return null;
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="sm:max-w-[625px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{t('build.editTool')}</DialogTitle>
                </DialogHeader>
                <form autoComplete="off" className="flex flex-col gap-4 py-6">
                    {renderFormContent()}
                    <DialogFooter>
                        <DialogClose>
                            <Button variant="outline" className="px-11" type="button">{t('build.cancel')}</Button>
                        </DialogClose>
                        <Button onClick={handleSubmit} className="px-11">{t('build.confirm')}</Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
});

export default ToolSet;
