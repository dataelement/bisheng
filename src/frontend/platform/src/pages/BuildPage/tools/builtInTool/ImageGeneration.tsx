import { Button } from '@bisheng/ui';
import { useState, type ChangeEvent, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { DialogClose, DialogFooter } from '@/components/bs-ui/dialog';
import { showApiError } from '@/controllers/request';
import { InputField } from './InputField';

type ImageSettings = {
    openai_api_base: string;
    openai_api_key: string;
    model: string;
    openai_proxy: string;
};

type Props = {
    formData?: Partial<ImageSettings> & { provider?: string; azure_endpoint?: string };
    onSubmit: (settings: ImageSettings & { provider: 'openai' }) => void | Promise<void>;
};

export default function ImageGeneration({ formData, onSubmit }: Props) {
    const { t } = useTranslation('tool');
    const legacyAzure = formData?.provider === 'azure' || Boolean(formData?.azure_endpoint);
    const [settings, setSettings] = useState<ImageSettings>(() => ({
        openai_api_base: legacyAzure ? 'https://api.openai.com/v1' : formData?.openai_api_base || 'https://api.openai.com/v1',
        openai_api_key: legacyAzure ? '' : formData?.openai_api_key || '',
        model: legacyAzure ? '' : formData?.model ?? (formData?.openai_api_key ? 'dall-e-3' : ''),
        openai_proxy: formData?.openai_proxy || '',
    }));
    const [errors, setErrors] = useState<Partial<Record<keyof ImageSettings, string>>>({});
    const [busy, setBusy] = useState(false);
    const fields: { name: keyof ImageSettings; type?: string; required?: boolean }[] = [
        { name: 'openai_api_base', required: true },
        { name: 'openai_api_key', type: 'password', required: true },
        { name: 'model', required: true },
        { name: 'openai_proxy' },
    ];

    const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
        const { name, value } = event.target;
        setSettings(previous => ({ ...previous, [name]: value }));
        setErrors(previous => ({ ...previous, [name]: undefined }));
    };

    const handleSubmit = async (event: FormEvent) => {
        event.preventDefault();
        if (busy) return;
        const nextErrors: Partial<Record<keyof ImageSettings, string>> = {};
        for (const field of fields) {
            if (field.required && !settings[field.name].trim()) nextErrors[field.name] = t('fieldCannotBeEmpty', { label: t(`imageGeneration.${field.name}`) });
        }
        try {
            const address = new URL(settings.openai_api_base);
            if (!['http:', 'https:'].includes(address.protocol) || !address.hostname || address.username || address.password || address.search || address.hash) throw new Error('address');
            const oldHost = new URL(formData?.openai_api_base || 'https://api.openai.com/v1').hostname;
            if (/^\*+$/.test(settings.openai_api_key) && (legacyAzure || address.hostname !== oldHost)) nextErrors.openai_api_key = t('imageGeneration.enterNewKey');
        } catch {
            nextErrors.openai_api_base = t('imageGeneration.invalidAddress');
        }
        setErrors(nextErrors);
        if (Object.keys(nextErrors).length) return;
        setBusy(true);
        try {
            await onSubmit({ ...settings, model: settings.model.trim(), openai_api_base: settings.openai_api_base.trim(), provider: 'openai' });
        } catch (error) {
            showApiError(error);
        } finally {
            setBusy(false);
        }
    };

    return <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {legacyAzure && <p className="text-sm text-muted-foreground">{t('imageGeneration.reconfigureAzure')}</p>}
        {fields.map(field => <InputField
            key={field.name}
            id={field.name}
            name={field.name}
            label={t(`imageGeneration.${field.name}`)}
            type={field.type || 'text'}
            required={field.required}
            value={settings[field.name]}
            onChange={handleChange}
            error={errors[field.name]}
            disabled={busy}
        />)}
        <DialogFooter className="mt-4">
            <DialogClose asChild><Button variant="outlined" type="button" disabled={busy}>{t('cancel', { ns: 'bs' })}</Button></DialogClose>
            <Button type="submit" disabled={busy}>{t('confirm', { ns: 'bs' })}</Button>
        </DialogFooter>
    </form>;
}
