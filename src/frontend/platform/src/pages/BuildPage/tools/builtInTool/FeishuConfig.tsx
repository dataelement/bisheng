import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

const defaultValues = {
    app_id: '',
    app_secret: '',
};

const FeishuConfigForm = ({ formData = {}, onSubmit }) => {
    const { t } = useTranslation();
    const [localFormData, setLocalFormData] = useState(() => ({ ...defaultValues, ...formData }));
    const [errors, setErrors] = useState({});

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;
        if (!localFormData.app_id) {
            formErrors.app_id = true;
            isValid = false;
        }
        if (!localFormData.app_secret) {
            formErrors.app_secret = true;
            isValid = false;
        }
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
        <form onSubmit={handleSubmit} className="flex flex-col gap-6" autoComplete="off">
            {/* App ID */}
            <InputField
                required
                label="App ID"
                tooltip="应用唯一的标识。"
                type="text"
                id="app_id"
                name="app_id"
                placeholder={''}
                value={localFormData.app_id}
                onChange={handleChange}
                error={errors.app_id}
            />

            {/* App Secret */}
            <InputField
                required
                label="App Secret"
                tooltip="应用的密钥，在创建应用时由平台生成。"
                type="password"
                id="app_secret"
                name="app_secret"
                placeholder={''}
                value={localFormData.app_secret}
                onChange={handleChange}
                error={errors.app_secret}
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

export default FeishuConfigForm;
