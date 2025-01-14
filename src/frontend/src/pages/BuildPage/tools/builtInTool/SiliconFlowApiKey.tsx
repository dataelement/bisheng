import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

const defaultValues = {
    siliconflow_api_key: '',
};

const SiliconFlowApiKeyForm = ({ formData = {}, onSubmit }) => {
    const { t } = useTranslation();
    const [localFormData, setLocalFormData] = useState(() => ({ ...defaultValues, ...formData }));
    const [errors, setErrors] = useState<any>({});

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;
        if (!localFormData.siliconflow_api_key) {
            formErrors.siliconflow_api_key = true;
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
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            {/* SiliconFlow API 密钥 */}
            <InputField
                required
                label="SiliconFlow API 密钥"
                type="password"
                id="siliconflow_api_key"
                name="siliconflow_api_key"
                placeholder={''}
                value={localFormData.siliconflow_api_key}
                onChange={handleChange}
                error={errors.siliconflow_api_key}
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

export default SiliconFlowApiKeyForm;
