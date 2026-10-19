import * as React from 'react';
import { useTranslation } from 'react-i18next';
import { Input, type InputProps } from '.';
import { QuestionTooltip } from '../tooltip';

interface NonNegativeInputProps extends InputProps {
    label?: string;
    tooltip?: string;
    error?: string;
    min?: number;
    max?: number;
    defaultValue?: number;
    inputClassName?: string;
    onValueChange?: (value: number) => void;
}

export const NonNegativeInput = React.forwardRef<HTMLInputElement, NonNegativeInputProps>(function NonNegativeInput(
    { className, inputClassName, label, tooltip, required, error, min = 0, max, defaultValue = 0,
        value, onValueChange, onChange, onBlur, id, maxLength: _maxLength, ...props }, ref,
) {
    void _maxLength;
    const { t } = useTranslation('bs');
    const [text, setText] = React.useState(String(value ?? defaultValue));
    const [internalError, setInternalError] = React.useState('');
    React.useEffect(() => {
        if (value !== undefined && value !== null) setText(String(value));
    }, [value]);

    const validate = (raw: string) => {
        if (raw === '') return t('sharedUi.required');
        if (!/^\d+$/.test(raw)) return t('sharedUi.nonNegativeInteger');
        if (Number(raw) < min) return t('sharedUi.minimum', { min });
        if (max !== undefined && Number(raw) > max) return t('sharedUi.maximum', { max });
        return '';
    };

    return <div className={className}>
        {label && <label htmlFor={id} className="bisheng-label flex items-center gap-1 mb-2">
            {label}
            {tooltip && <QuestionTooltip content={tooltip} />}
            {required && <span className="bisheng-tip">*</span>}
        </label>}
        <Input {...props} ref={ref} id={id} type="text" inputMode="numeric" value={text}
            required={required} className={inputClassName} aria-invalid={Boolean(error || internalError) || undefined}
            onChange={(event) => {
                const raw = event.target.value;
                if (!/^\d*$/.test(raw) || (raw.length > 1 && raw.startsWith('0'))) return;
                setText(raw);
                const nextError = raw === '' ? '' : validate(raw);
                setInternalError(nextError);
                if (raw !== '' && !nextError) onValueChange?.(Number(raw));
                onChange?.(event);
            }}
            onBlur={(event) => {
                if (text.trim() === '') {
                    setText(String(defaultValue));
                    setInternalError('');
                    onValueChange?.(defaultValue);
                } else setInternalError(validate(text));
                onBlur?.(event);
            }} />
        {(error || internalError) && <p className="bisheng-tip mt-1">{error || internalError}</p>}
    </div>;
});
