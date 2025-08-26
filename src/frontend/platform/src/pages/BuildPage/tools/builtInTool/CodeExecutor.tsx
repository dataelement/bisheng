import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from "react-i18next";
import {InputField, SelectField} from "./InputField";
import { PassInput } from '@/components/bs-ui/input';
import { QuestionTooltip } from '@/components/bs-ui/tooltip';

const Dalle3ToolForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation();
      const domainRef = useRef(null);
    const apiKeyRef = useRef(null);

  const [localFormData, setLocalFormData] = useState(() => {
        const executionMode = formData.type || 'local';
 const serviceProvider = formData.config?.e2b?.type || 'private';
        const domain = formData.config?.e2b?.domain || '';
        const apiKey = formData.config?.e2b?.api_key || '';

        return {
            executionMode,
            serviceProvider,
            domain,
            apiKey
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
            if (localFormData.serviceProvider === 'private') {
                if (!localFormData.domain) {
                    formErrors.domain = 'domain 不能为空';
                    isValid = false;
                }
            }
            if (!localFormData.apiKey) {
                formErrors.apiKey = 'API Key 不能为空';
                isValid = false;
            }
        }
        setErrors(formErrors);
        return isValid;
    };

  const handleSubmit = (e) => {
        e.preventDefault();
        if (validateForm()) {
            const submitData = {
                type: localFormData.executionMode
            };

            if (localFormData.executionMode === 'e2b') {
                submitData.config = {
                    e2b: {
                        type: localFormData.serviceProvider,
                        api_key: localFormData.apiKey
                    }
                };
                
                if (localFormData.serviceProvider === 'private') {
                    submitData.config.e2b.domain = localFormData.domain;
                }
            }

            onSubmit(submitData);
        }
    };

    return (
        <>
            <div className="mb-6">
                <Label className=" mb-3 mt-4 block">代码执行方式</Label>
                <RadioGroup 
                    value={localFormData.executionMode} 
                    className="flex gap-6" 
                    onValueChange={handleExecutionModeChange}
                >
                    <div className="flex items-center space-x-2">
                        <RadioGroupItem value="local" id="execution-local" />
                        <Label htmlFor="execution-local">本机运行</Label>
                    </div>
                    <div className="flex items-center space-x-2">
                        <RadioGroupItem value="e2b" id="execution-e2b" />
                        <Label htmlFor="execution-e2b">E2B沙箱运行</Label>
                    </div>
                </RadioGroup>
            </div>
            {localFormData.executionMode === 'e2b' && (
                <div className="space-y-4">
                    <div>
                        <Label className="mb-3 block">服务提供方</Label>
                        <RadioGroup 
                            value={localFormData.serviceProvider} 
                            className="flex gap-6" 
                            onValueChange={handleServiceProviderChange}
                        >
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="private" id="provider-private" />
                                <Label htmlFor="provider-private" >自托管 <QuestionTooltip content={'需要提前在您的本地环境部署 E2B ，并将 domain 指向自托管地址，API Key 鉴权由您部署的 E2B 后台处理。'} /></Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="official" id="provider-official" />
                                <Label htmlFor="provider-official">官方云 <QuestionTooltip content={'使用 E2B 官方云服务，需要从 E2B 官方获取 API Key。'} /></Label>
                            </div>
                        </RadioGroup>
                    </div>
                              {localFormData.serviceProvider === 'private' && (
                
                      <InputField
                            required
                            label={<Label>Domain</Label>}
                            id="e2b-domain-input"
                            name="domain"
                            placeholder="https://e2b.internal.mycorp"
                            value={localFormData.domain}
                            onChange={handleChange}
                            error={errors.domain}
                        />
                    )}
{/* 
                    <InputField
                        required
                        label={<Label>API Key</Label>}
                        type="password"
                        id="e2b-apikey-input"
                        name="apiKey"
                        placeholder="请输入API Key"
                        value={localFormData.apiKey}
                        onChange={handleChange}
                        error={errors.apiKey}
                    /> */}
                    <PassInput
                     required
                      id="e2b-apikey-input"
                     label={<Label>API Key</Label>}
                       placeholder="请输入API Key"
                    type='text'
                      name="apiKey"
                        onChange={handleChange}
                     value={localFormData.apiKey}
                      error={errors.apiKey}
                    >
                        
                    </PassInput>
                </div>
            )}

            <DialogFooter className="mt-6">
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('build.cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" onClick={handleSubmit}>
                    {t('save')}
                </Button>
            </DialogFooter>
        </>
    );
};

export default Dalle3ToolForm;