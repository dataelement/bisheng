import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

// 代码由毕昇生成
export default function ToolSet({ open, name, onOpenChange }) {
    const { t } = useTranslation();
    const [formData, setFormData] = useState({
        provider: 'openai',
        apiKey: '',
        baseUrl: 'https://api.openai.com/v1',
        proxy: '',
        subscriptionKey: '',
        searchUrl: 'https://api.bing.microsoft.com/v7.0/search',
        deploymentName: '',
        azureEndpoint: '',
        apiVersion: ''
    });

    useEffect(() => {
        setFormData({
            provider: 'openai',
            apiKey: '',
            baseUrl: 'https://api.openai.com/v1',
            proxy: '',
            subscriptionKey: '',
            searchUrl: 'https://api.bing.microsoft.com/v7.0/search',
            deploymentName: '',
            azureEndpoint: '',
            apiVersion: ''
        });
    }, [name]);

    const [errors, setErrors] = useState<any>({});

    const validateField = (name, value) => {
        if (!value) return t('build.fieldRequired');
        return '';
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        const error = validateField(name, value);

        setFormData(prev => ({ ...prev, [name]: value }));
        setErrors(prev => ({ ...prev, [name]: error }));
    };

    const handleProviderChange = (value) => {
        setFormData(prev => ({ ...prev, provider: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;

        const fieldsToValidate = [];
        if (name === 'Dalle3绘画') {
            fieldsToValidate.push('apiKey');
            if (formData.provider === 'openai') {
                fieldsToValidate.push('baseUrl', 'proxy');
            } else {
                fieldsToValidate.push('deploymentName', 'azureEndpoint', 'apiVersion');
            }
        } else if (name === 'Bing web搜索') {
            fieldsToValidate.push('subscriptionKey', 'searchUrl');
        } else if (name === '天眼查') {
            fieldsToValidate.push('apiKey');
        }

        fieldsToValidate.forEach((key) => {
            const error = validateField(key, formData[key]);
            if (error) {
                formErrors[key] = error;
                isValid = false;
            }
        });

        setErrors(formErrors);
        return isValid;
    };

    const { message, toast } = useToast();

    const handleSubmit = (e) => {
        e.preventDefault();
        const isValid = validateForm();
        if (!isValid) return toast({
            title: t('prompt'),
            variant: 'error',
            description: Object.keys(errors).map(key => errors[key]).join(', '),
        });

        const fieldsToSubmit = {};
        if (name === 'Dalle3绘画') {
            fieldsToSubmit.apiKey = formData.apiKey;
            if (formData.provider === 'openai') {
                fieldsToSubmit.baseUrl = formData.baseUrl;
                fieldsToSubmit.proxy = formData.proxy;
            } else {
                fieldsToSubmit.deploymentName = formData.deploymentName;
                fieldsToSubmit.azureEndpoint = formData.azureEndpoint;
                fieldsToSubmit.apiVersion = formData.apiVersion;
            }
        } else if (name === 'Bing web搜索') {
            fieldsToSubmit.subscriptionKey = formData.subscriptionKey;
            fieldsToSubmit.searchUrl = formData.searchUrl;
        } else if (name === '天眼查') {
            fieldsToSubmit.apiKey = formData.apiKey;
        }

        handleSave(fieldsToSubmit);
    };

    const handleSave = (form) => {
        console.log('form :>> ', form);
        // api
    }

    const renderFormContent = () => {
        switch (name) {
            case 'Dalle3绘画':
                return (
                    <>
                        <div className="">
                            <RadioGroup defaultValue="openai" className="flex gap-6 mt-2" onValueChange={handleProviderChange}>
                                <div className="flex items-center space-x-2">
                                    <RadioGroupItem value="openai" id="provider-openai" />
                                    <Label htmlFor="provider-openai">OpenAI</Label>
                                </div>
                                <div className="flex items-center space-x-2">
                                    <RadioGroupItem value="azure" id="provider-azure" />
                                    <Label htmlFor="provider-azure">Azure</Label>
                                </div>
                            </RadioGroup>
                        </div>
                        {formData.provider === 'openai' ? (
                            <>
                                <div className="">
                                    <label htmlFor="apiKey" className="bisheng-label">OpenAI API Key<span className="bisheng-tip">*</span></label>
                                    <Input type="password" id="apiKey" name="apiKey" placeholder={t('build.enterApiKey')} className="mt-2" value={formData.apiKey} onChange={handleChange} />
                                    {errors.apiKey && <p className="bisheng-tip mt-1">{errors.apiKey}</p>}
                                </div>
                                <div className="">
                                    <label htmlFor="baseUrl" className="bisheng-label">OpenAI Base URL</label>
                                    <Input type="text" id="baseUrl" name="baseUrl" placeholder={t('build.enterBaseUrl')} className="mt-2" value={formData.baseUrl} onChange={handleChange} />
                                    {errors.baseUrl && <p className="bisheng-tip mt-1">{errors.baseUrl}</p>}
                                </div>
                                <div className="">
                                    <label htmlFor="proxy" className="bisheng-label">OpenAI Proxy</label>
                                    <Input type="text" id="proxy" name="proxy" placeholder={t('build.enterProxy')} className="mt-2" value={formData.proxy} onChange={handleChange} />
                                    {errors.proxy && <p className="bisheng-tip mt-1">{errors.proxy}</p>}
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="">
                                    <label htmlFor="apiKey" className="bisheng-label">Azure OpenAI API Key<span className="bisheng-tip">*</span></label>
                                    <Input type="password" id="apiKey" name="apiKey" placeholder={t('build.enterApiKey')} className="mt-2" value={formData.apiKey} onChange={handleChange} />
                                    {errors.apiKey && <p className="bisheng-tip mt-1">{errors.apiKey}</p>}
                                </div>
                                <div className="">
                                    <label htmlFor="deploymentName" className="bisheng-label">Deployment Name<span className="bisheng-tip">*</span></label>
                                    <Input type="text" id="deploymentName" name="deploymentName" placeholder={t('build.enterDeploymentName')} className="mt-2" value={formData.deploymentName} onChange={handleChange} />
                                    {errors.deploymentName && <p className="bisheng-tip mt-1">{errors.deploymentName}</p>}
                                </div>
                                <div className="">
                                    <label htmlFor="azureEndpoint" className="bisheng-label">Azure Endpoint<span className="bisheng-tip">*</span></label>
                                    <Input type="text" id="azureEndpoint" name="azureEndpoint" placeholder="格式示例：https://xxx.openai.azure.com/" className="mt-2" value={formData.azureEndpoint} onChange={handleChange} />
                                    {errors.azureEndpoint && <p className="bisheng-tip mt-1">{errors.azureEndpoint}</p>}
                                </div>
                                <div className="">
                                    <label htmlFor="apiVersion" className="bisheng-label">Openai API Version<span className="bisheng-tip">*</span></label>
                                    <Input type="text" id="apiVersion" name="apiVersion" placeholder="格式示例：2024-02-01" className="mt-2" value={formData.apiVersion} onChange={handleChange} />
                                    {errors.apiVersion && <p className="bisheng-tip mt-1">{errors.apiVersion}</p>}
                                </div>
                            </>
                        )}
                    </>
                );
            case 'Bing web搜索':
                return (
                    <>
                        <div className="">
                            <label htmlFor="subscriptionKey" className="bisheng-label">Bing Subscription Key<span className="bisheng-tip">*</span></label>
                            <Input type="password" id="subscriptionKey" name="subscriptionKey" placeholder={t('build.enterSubscriptionKey')} className="mt-2" value={formData.subscriptionKey} onChange={handleChange} />
                            {errors.subscriptionKey && <p className="bisheng-tip mt-1">{errors.subscriptionKey}</p>}
                        </div>
                        <div className="">
                            <label htmlFor="searchUrl" className="bisheng-label">Bing Search URL<span className="bisheng-tip">*</span></label>
                            <Input type="text" id="searchUrl" name="searchUrl" placeholder={t('build.enterSearchUrl')} className="mt-2" value={formData.searchUrl} onChange={handleChange} />
                            {errors.searchUrl && <p className="bisheng-tip mt-1">{errors.searchUrl}</p>}
                        </div>
                    </>
                );
            case '天眼查':
                return (
                    <>
                        <div className="">
                            <label htmlFor="apiKey" className="bisheng-label">API Key<span className="bisheng-tip">*</span></label>
                            <Input type="password" id="apiKey" name="apiKey" placeholder={t('build.enterApiKey')} className="mt-2" value={formData.apiKey} onChange={handleChange} />
                            {errors.apiKey && <p className="bisheng-tip mt-1">{errors.apiKey}</p>}
                        </div>
                    </>
                );
            default:
                return null;
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[625px] bg-background-login">
                <DialogHeader>
                    <DialogTitle>{t('build.editTool')}</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="flex flex-col gap-4 py-6">
                    {renderFormContent()}
                    <DialogFooter>
                        <DialogClose>
                            <Button variant="outline" className="px-11" type="button">{t('build.cancel')}</Button>
                        </DialogClose>
                        <Button type="submit" className="px-11">{t('build.confirm')}</Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}
