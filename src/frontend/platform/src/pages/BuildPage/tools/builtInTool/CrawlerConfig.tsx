import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from "@/components/bs-ui/dialog";
import { useState } from 'react';
import { useTranslation } from "react-i18next";
import { InputField } from "./InputField";

const defaultValues = {
    api_key: '',
    base_url: 'https://api.firecrawl.dev',
    timeout: 30000,
    maxdepth: 2,
    limit: 100,
};

const CrawlerConfigForm = ({ formData, onSubmit }) => {
    const { t } = useTranslation('tool');
    const [localFormData, setLocalFormData] = useState(() => ({ ...defaultValues, ...formData }));
    const [errors, setErrors] = useState({});

    const handleChange = (e) => {
        const { name, value } = e.target;
        setLocalFormData((prev) => ({ ...prev, [name]: value }));
    };

    const validateForm = () => {
        const formErrors = {};
        let isValid = true;
        if (!localFormData.api_key) {
            formErrors.api_key = true;
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
            {/* API Key */}
            <InputField
                required
                label="API Key"
                type="password"
                id="api_key"
                name="api_key"
                placeholder={t('enterApiKey')}
                value={localFormData.api_key}
                onChange={handleChange}
                error={errors.api_key}
            />

            {/* Base URL */}
            <InputField
                label="Base URL"
                id="base_url"
                name="base_url"
                placeholder="https://api.firecrawl.dev"
                value={localFormData.base_url}
                onChange={handleChange}
            />

            {/* Timeout */}
            <InputField
                label="Timeout (ms)"
                type="number"
                id="timeout"
                name="timeout"
                tooltip={t('timeoutTooltip')}
                value={localFormData.timeout}
                onChange={handleChange}
            />

            <p className='border-t dark:border-gray-700 pt-4 text-sm font-bold'>
                {t('deepCrawlDetailConfigDescription')}
            </p>

            {/* Maxdepth */}
            <InputField
                label="Maxdepth"
                type="number"
                id="maxdepth"
                name="maxdepth"
                tooltip={t('maxdepthTooltip')}
                value={localFormData.maxdepth}
                onChange={handleChange}
            />

            {/* Limit */}
            <InputField
                label="Limit"
                type="number"
                id="limit"
                name="limit"
                tooltip={t('limitTooltip')}
                value={localFormData.limit}
                onChange={handleChange}
            />

            {/* Dialog Footer */}
            <DialogFooter>
                <DialogClose>
                    <Button variant="outline" className="px-11" type="button">
                        {t('cancel', { ns: 'bs' })}
                    </Button>
                </DialogClose>
                <Button className="px-11" type="submit">
                    {t('save', { ns: 'bs' })}
                </Button>
            </DialogFooter>
        </form>
    );
};

export default CrawlerConfigForm;
