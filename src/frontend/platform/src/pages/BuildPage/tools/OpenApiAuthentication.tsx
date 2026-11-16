import { Input, Radio, RadioGroup } from '@bisheng/ui';
import { useTranslation } from 'react-i18next';

export interface OpenApiAuthenticationValue {
    authMethod: string;
    authType: string;
    apiLocation: string;
    parameter: string;
    apiKey: string;
}
interface Props {
    id: string;
    value: OpenApiAuthenticationValue;
    onChange: (value: OpenApiAuthenticationValue) => void;
    declaredAuth?: { location: string; name: string };
    credentialPlaceholder?: string;
    customOnly?: boolean;
}

/** Shared authentication controls for custom tools and custom search. */
export function OpenApiAuthentication({ id, value, onChange, declaredAuth, credentialPlaceholder, customOnly = false }: Props) {
    const { t } = useTranslation();
    const update = (change: Partial<OpenApiAuthenticationValue>) => onChange({ ...value, ...change });
    const choices = (name: string, selected: string, options: { value: string; label: string; disabled?: boolean }[], onValueChange: (next: string) => void) => <RadioGroup id={`${id}-${name}`} aria-label={String(t('tools.' + name))} value={selected} className="flex flex-wrap gap-4" onValueChange={onValueChange}>
        {options.map(option => <div key={option.value} className="flex items-center space-x-2">
            <Radio id={`${id}-${name}-${option.value}`} value={option.value} disabled={option.disabled} />
            <label htmlFor={`${id}-${name}-${option.value}`}>{option.label}</label>
        </div>)}
    </RadioGroup>;
    return <div className="space-y-3">
        <label className="bisheng-label">{t('tools.authenticationType')}</label>
        {choices('authType', value.authMethod, [{ value: 'none', label: String(t('tools.none')), disabled: Boolean(declaredAuth?.location) }, { value: 'apikey', label: String(t('tools.apiKey')) }], authMethod => update({ authMethod }))}
        {value.authMethod === 'apikey' && <>
            {!customOnly && choices('authTypeLabel', value.authType, ['basic', 'bearer', 'custom'].map(authType => ({ value: authType, label: String(t('tools.' + authType)) })), authType => update({ authType }))}
            {value.authType === 'custom' && <>
                <label className="bisheng-label">{t('tools.apiLocationLabel')}</label>
                {choices('apiLocationLabel', value.apiLocation, (declaredAuth?.location ? [declaredAuth.location] : ['header', 'query', ...(customOnly ? ['cookie'] : [])]).map(location => ({ value: location, label: location === 'cookie' ? 'Cookie' : String(t('tools.' + location)) })), apiLocation => update({ apiLocation }))}
                <label htmlFor={`${id}-parameter`} className="bisheng-label">{t('tools.parameterName')}</label>
                <Input id={`${id}-parameter`} value={value.parameter} readOnly={Boolean(declaredAuth?.name)} placeholder={String(t('tools.parameterPlaceholder'))} onChange={event => update({ parameter: event.target.value })} />
            </>}
            <label htmlFor={`${id}-key`} className="bisheng-label">{t('tools.apiKeyLabel')}</label>
            <Input id={`${id}-key`} type="password" autoComplete="off" value={value.apiKey} placeholder={credentialPlaceholder || String(t('tools.apiKeyPlaceholder'))} onChange={event => update({ apiKey: event.target.value })} />
        </>}
    </div>;
}
