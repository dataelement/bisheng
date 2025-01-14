import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField, SelectField } from "./InputField";

const defaultValues = {
    email_account: '',
    email_password: '',
    smtp_server: '',
    smtp_port: '',
    encrypt_method: '无加密', // 默认值
};

const EmailConfigForm = ({ formData = {}, onSubmit }) => {
    const { t } = useTranslation();
    const [localFormData, setLocalFormData] = useState(() => ({ ...defaultValues, ...formData }));
    const [errors, setErrors] = useState({});

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const handleSelectChange = (name, value) => {
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;
        ['email_account', 'email_password', 'smtp_server', 'smtp_port', 'encrypt_method'].forEach((field) => {
            if (!localFormData[field]) {
                formErrors[field] = true;
                isValid = false;
            }
        });
        setErrors(formErrors);
        return isValid;
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (validateForm()) {
            onSubmit(localFormData);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            {/* Email Account */}
            <InputField
                required
                label="发件人邮箱账号"
                type="text"
                id="email_account"
                name="email_account"
                placeholder={''}
                value={localFormData.email_account}
                onChange={handleChange}
                error={errors.email_account}
            />

            {/* Email Password */}
            <InputField
                required
                label="发件人邮箱密码"
                type="password"
                id="email_password"
                name="email_password"
                placeholder={''}
                value={localFormData.email_password}
                onChange={handleChange}
                error={errors.email_password}
            />

            {/* SMTP Server */}
            <InputField
                required
                label="发信 SMTP 服务器地址"
                type="text"
                id="smtp_server"
                name="smtp_server"
                placeholder={''}
                value={localFormData.smtp_server}
                onChange={handleChange}
                error={errors.smtp_server}
            />

            {/* SMTP Port */}
            <InputField
                required
                label="发信 SMTP 服务器端口"
                type="text"
                id="smtp_port"
                name="smtp_port"
                placeholder={''}
                value={localFormData.smtp_port}
                onChange={handleChange}
                error={errors.smtp_port}
            />

            {/* Encrypt Method */}
            <SelectField
                required
                label="发信 服务器加密方式"
                id="encrypt_method"
                name="encrypt_method"
                value={localFormData.encrypt_method}
                onChange={(value) => handleSelectChange('encrypt_method', value)}
                options={[
                    { label: '无加密', value: '无加密' },
                    { label: 'SSL 加密', value: 'SSL 加密' },
                    { label: 'STARTTLS 加密', value: 'STARTTLS 加密' },
                ]}
                error={errors.encrypt_method}
            />

            {/* Dialog Footer */}
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t('save')}
                </Button>
            </DialogFooter>
        </form>
    );
};

export default EmailConfigForm;
