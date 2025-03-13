import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useEffect, useState } from 'react';
import { useTranslation } from "react-i18next";
import {InputField, SelectField} from "./InputField";

const temp = {
    bing_subscription_key: '',
    bing_search_url: 'https://api.bing.microsoft.com/v7.0/search',
}

const BingToolForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation();
    const [localFormData, setLocalFormData] = useState(() => ({ ...temp, ...formData }));
    const [errors, setErrors] = useState({});

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;
        if (!localFormData.bing_subscription_key) {
            formErrors.bing_subscription_key = true;
            isValid = false;
        }
        if (!localFormData.bing_search_url) {
            formErrors.bing_search_url = true;
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
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <InputField
                required
                label="Bing Subscription Key"
                type="password"
                id="bing_subscription_key"
                name="bing_subscription_key"
                placeholder={t('build.enterSubscriptionKey')}
                value={localFormData.bing_subscription_key}
                onChange={handleChange}
                error={errors.bing_subscription_key}
            />
            <InputField
                required
                label="Bing Search URL"
                id="bing_search_url"
                name="bing_search_url"
                placeholder={t('build.enterSearchUrl')}
                value={localFormData.bing_search_url}
                onChange={handleChange}
                error={errors.bing_search_url}
            />

            {/* 这里是 DialogFooter */}
            <DialogFooter>
                <DialogClose>
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

export default BingToolForm;

