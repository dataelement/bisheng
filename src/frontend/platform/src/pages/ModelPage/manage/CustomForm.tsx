import { Input, Select } from '@bisheng/ui';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { Label } from '@/components/bs-ui/label';
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getModelProviders } from './modelProviderFields';
import { configWithDefaults, getConfigError, getSpeechFields, speechDocs, speechProviders } from './speechConfig';
import type { ConfigField, ProviderConfig } from './speechConfig';

interface CustomFormProps {
    showDefault: boolean;
    provider: string;
    formData: ProviderConfig;
    modelTypes: string[];
    providerName?: string;
    apiKeySite?: string;
}
export interface CustomFormHandle {
    getData(): [ProviderConfig, string];
}
interface FormFieldProps {
    field: ConfigField;
    value: string;
    providerName?: string;
    apiKeySite?: string;
    onChange: (key: string, value: string) => void;
}

function FormField({ field, value, providerName, apiKeySite, onChange }: FormFieldProps) {
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();
    return <div className="space-y-2">
        <Label className="bisheng-label" htmlFor={field.key}>
            {field.label}{field.required && ' *'}
            {apiKeySite && field.label.includes('API Key') && <a href={apiKeySite} target="_blank" rel="noreferrer" className="ml-1 text-primary">
                ({t('model.getApiKey', { provider: providerName })})
            </a>}
        </Label>
        {field.options ? <Select
            {...selectLabels}
            id={field.key}
            aria-label={field.label}
            options={field.options.filter(option => option.value != null && option.value !== '')}
            value={value || null}
            onChange={next => onChange(field.key, next == null ? '' : String(next))}
        /> : <Input id={field.key} type={field.type || 'text'} autoComplete="off" placeholder={field.example ? t('model.formatExample', { example: field.example }) : field.placeholder} value={value}
            onChange={event => onChange(field.key, event.target.value)} required={field.required} />}
    </div>;
}

export const CustomForm = forwardRef<CustomFormHandle, CustomFormProps>(function CustomForm(
    { showDefault, provider, formData, modelTypes, providerName, apiKeySite }, ref,
) {
    const { t } = useTranslation();
    const [form, setForm] = useState(formData);
    const hasSpeech = speechProviders.includes(provider) && modelTypes.includes('asr');
    const speechOnly = hasSpeech && modelTypes.every(type => type === 'asr');
    const commonFields = speechOnly ? [] : getModelProviders()[provider] || [];
    const speechFields = hasSpeech ? getSpeechFields(provider, form, t) : [];
    const fields = [...commonFields, ...speechFields];
    const values = configWithDefaults(form, fields, showDefault);
    const handleChange = (key: string, value: string) => setForm(previous => ({ ...previous, [key]: value }));
    useEffect(() => { setForm(formData); }, [formData]);
    useImperativeHandle(ref, () => ({
        getData: () => [values, getConfigError(values, fields)],
    }));
    return <div className="space-y-4">
        {commonFields.map(field => <FormField key={field.key} field={field} value={values[field.key] || ''}
            providerName={providerName} apiKeySite={apiKeySite} onChange={handleChange} />)}
        {hasSpeech && <div className="my-3 rounded border p-3">
            <Label className="bisheng-label">{t('model.speechCredentials')}</Label>
            <p className="mb-2 text-xs text-muted-foreground">{t('model.speechCredentialsHint')}</p>
            {speechFields.map(field => <FormField key={field.key} field={field} value={values[field.key] || ''} onChange={handleChange} />)}
            <a href={speechDocs[provider]} target="_blank" rel="noreferrer" className="text-xs text-primary">{t('model.speechDocs')}</a>
        </div>}
    </div>;
});
