import { Button } from '@/components/bs-ui/button';
import { DialogClose, DialogFooter } from '@/components/bs-ui/dialog';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { InputField } from './InputField';

const defaultValues = {
    minimax_api_key: '',
    minimax_base_url: 'https://api.minimax.io',
};

export function MiniMaxConfig({ formData = {}, onSubmit }) {
    const { t } = useTranslation('tool');
    const [localFormData, setLocalFormData] = useState(() => ({ ...defaultValues, ...formData }));
    const [errors, setErrors] = useState<Record<string, boolean>>({});

    const handleChange = (event) => {
        const { name, value } = event.target;
        setLocalFormData((previous) => ({ ...previous, [name]: value }));
    };

    const handleSubmit = (event) => {
        event.preventDefault();
        const nextErrors = {
            minimax_api_key: !localFormData.minimax_api_key,
            minimax_base_url: !localFormData.minimax_base_url,
        };
        setErrors(nextErrors);
        if (!Object.values(nextErrors).some(Boolean)) onSubmit(localFormData);
    };

    return (
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
            <InputField required label={t('minimaxApiKeyLabel')} type="password" id="minimax_api_key" name="minimax_api_key" placeholder="" value={localFormData.minimax_api_key} onChange={handleChange} error={errors.minimax_api_key} />
            <InputField required label={t('minimaxApiBaseUrlLabel')} type="url" id="minimax_base_url" name="minimax_base_url" placeholder="https://api.minimax.io" value={localFormData.minimax_base_url} onChange={handleChange} error={errors.minimax_base_url} />
            <DialogFooter>
                <DialogClose><Button variant="outline" className="px-11" type="button">{t('cancel', { ns: 'bs' })}</Button></DialogClose>
                <Button className="px-11" type="submit">{t('save', { ns: 'bs' })}</Button>
            </DialogFooter>
        </form>
    );
}
