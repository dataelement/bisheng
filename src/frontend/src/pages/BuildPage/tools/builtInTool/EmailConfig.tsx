import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField, SelectField } from "./InputField";

// Default values for the form
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

    // Handle input changes
    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    // Handle select field changes
    const handleSelectChange = (name, value) => {
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    // Validate the form inputs
    const validateForm = () => {
        const formErrors = {};
        let isValid = true;

        // Email account validation
        const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
        if (!localFormData.email_account) {
            formErrors.email_account = true;
            isValid = false;
        } else if (!emailRegex.test(localFormData.email_account)) {
            formErrors.email_account = '请输入有效的邮箱地址';
            isValid = false;
        }

        if (!localFormData.email_password) {
            formErrors.email_password = true;
            isValid = false;
        }

        // SMTP server validation (check for valid domain or IP address)
        const smtpServerRegex = /^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,6}$|^(?:\d{1,3}\.){3}\d{1,3}$/;
        // This regex allows valid domain names (e.g., smtp.example.com) or valid IPv4 addresses (e.g., 192.168.1.1)
        if (!localFormData.smtp_server) {
            formErrors.smtp_server = true;
            isValid = false;
        } else if (!smtpServerRegex.test(localFormData.smtp_server)) {
            formErrors.smtp_server = '请输入有效的SMTP服务器地址';
            isValid = false;
        }

        // SMTP port validation (must be a number between 1 and 65535)
        const smtpPort = parseInt(localFormData.smtp_port);
        if (!localFormData.smtp_port) {
            formErrors.smtp_port = true;
            isValid = false;
        } else if (isNaN(smtpPort) || smtpPort < 1 || smtpPort > 65535) {
            formErrors.smtp_port = '请输入有效的端口号';
            isValid = false;
        }

        // Encrypt method validation
        if (!localFormData.encrypt_method) {
            formErrors.encrypt_method = true;
            isValid = false;
        }

        setErrors(formErrors);
        return isValid;
    };

    // Handle form submit
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
                label="email_account（发件人邮箱账号）"
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
                label="email_password（发件人邮箱密码）"
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
                label="smtp_server（发信 SMTP 服务器地址）"
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
                label="smtp_port（发信 SMTP 服务器端口）"
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
                label="encrypt_method（发信 服务器加密方式）"
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
