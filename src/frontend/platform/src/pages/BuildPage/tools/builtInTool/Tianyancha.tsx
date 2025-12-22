import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useEffect, useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

const TianyanchaToolForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation();

    // Initialize with proxy field
    const [localFormData, setLocalFormData] = useState(() => ({
        api_key: '',
        proxy: '',
        ...formData
    }));
    const [errors, setErrors] = useState({});

    useEffect(() => {
        setLocalFormData((prev) => ({ ...prev, ...formData }));
    }, [formData]);

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;
        if (!localFormData.api_key) {
            formErrors.api_key = 'API key is required';
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
        <form onSubmit={handleSubmit} className="flex flex-col gap-4" autoComplete="off">
            <InputField
                required
                label="API Key"
                type="password"
                id="api_key"
                name="api_key"
                placeholder={t('build.enterApiKey')}
                value={localFormData.api_key}
                onChange={handleChange}
                error={errors.api_key}
            />

            <div className="relative">
                <InputField
                    id="proxy"
                    label="proxy"
                    name="proxy"
                    tooltip={t('build.proxyDescription')}
                    placeholder=''
                    value={localFormData.proxy}
                    onChange={handleChange}
                // No 'label' prop here because we rendered a custom one with the icon above
                />
            </div>

            <DialogFooter>
                <DialogClose asChild>
                    <Button variant="outline" className="px-11" type="button">
                        {t('build.cancel')}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t('build.confirm')}
                </Button>
            </DialogFooter>
        </form>
    );
};

export default TianyanchaToolForm;