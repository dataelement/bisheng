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
        // 从表单数据中提取所有配置
        const executionMode = formData.type || 'local';
        const serviceProvider = formData.config?.e2b?.type || 'private';
        
        // 同时获取两种配置
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
            // 验证当前选中的服务提供商配置
            if (localFormData.serviceProvider === 'private') {
                if (!localFormData.privateDomain) {
                    formErrors.privateDomain = 'Domain 不能为空';
                    isValid = false;
                }
                if (!localFormData.privateApiKey) {
                    formErrors.privateApiKey = 'API Key 不能为空';
                    isValid = false;
                }
            } else {
                if (!localFormData.officialApiKey) {
                    formErrors.officialApiKey = 'API Key 不能为空';
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
            // 构建完整的表单数据，同时保存两种配置
            const submitData = {
                type: localFormData.executionMode,
                config: {
                    // 保存当前选择的服务提供商类型
                    e2b: {
                        type: localFormData.serviceProvider
                    },
                    // 同时保存两种配置
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
            
            {/* 只在选择E2B沙箱运行时显示配置 */}
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
                        placeholder="请输入API Key"
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