import { InputNumber, type InputNumberError, type InputNumberProps } from '@bisheng/ui';
import * as React from 'react';
import { useTranslation } from 'react-i18next';

import { QuestionHint as QuestionTooltip } from '@/components/bs-comp/QuestionHint';

interface NonNegativeInputProps
    extends Omit<InputNumberProps, 'value' | 'defaultValue' | 'onChange' | 'min' | 'max' | 'step' | 'precision' | 'errorMessage' | 'className'> {
    label?: string;
    tooltip?: string;
    /** Outside verdict from the form; shown in place of the field's own range message. */
    error?: string;
    min?: number;
    max?: number;
    /** Restored (and reported) when the field is left empty. */
    defaultValue?: number;
    /** Callers may hold an empty string while their state is unset. */
    value?: number | '' | null;
    className?: string;
    /** Reports only valid integers inside [min, max]. */
    onValueChange?: (value: number) => void;
}

/**
 * A non-negative integer field on the shared InputNumber: it never rewrites what is typed,
 * reports range / decimal problems on blur, and falls back to `defaultValue` when left empty.
 */
export const NonNegativeInput = React.forwardRef<HTMLInputElement, NonNegativeInputProps>(function NonNegativeInput(
    { className, label, tooltip, required, error, min = 0, max, defaultValue = 0, value, onValueChange, onBlur, id, ...props }, ref,
) {
    const { t } = useTranslation('bs');
    const toNumber = (v: number | '' | null | undefined) => (typeof v === 'number' ? v : null);
    const [current, setCurrent] = React.useState<number | null>(toNumber(value) ?? defaultValue);
    React.useEffect(() => {
        if (typeof value === 'number') setCurrent(value);
    }, [value]);
    // Whether the field is showing its own range / decimal message under the box.
    const [fieldErrorShown, setFieldErrorShown] = React.useState(false);

    const errorMessage = (fieldError: InputNumberError) => {
        if (error) return error;
        if (fieldError.type === 'precision') return t('sharedUi.nonNegativeInteger');
        return current !== null && current < min ? t('sharedUi.minimum', { min }) : t('sharedUi.maximum', { max });
    };

    return <div className={className}>
        {label && <label htmlFor={id} className="bisheng-label flex items-center gap-1 mb-2">
            {label}
            {tooltip && <QuestionTooltip content={tooltip} />}
            {required && <span className="bisheng-tip">*</span>}
        </label>}
        <InputNumber
            {...props}
            ref={ref}
            id={id}
            value={current}
            min={min}
            max={max}
            step={1}
            precision={0}
            required={required}
            aria-required={required || undefined}
            status={error ? 'error' : props.status}
            increaseLabel={props.increaseLabel ?? t('sharedUi.increase')}
            decreaseLabel={props.decreaseLabel ?? t('sharedUi.decrease')}
            errorMessage={errorMessage}
            onErrorChange={(fieldError) => {
                setFieldErrorShown(fieldError !== null);
                props.onErrorChange?.(fieldError);
            }}
            onChange={(next, detail) => {
                setCurrent(next);
                if (next !== null && !detail.error) onValueChange?.(next);
            }}
            onBlur={(event) => {
                if (current === null) {
                    setCurrent(defaultValue);
                    onValueChange?.(defaultValue);
                }
                onBlur?.(event);
            }}
        />
        {error && !fieldErrorShown && <p className="bisheng-tip mt-1">{error}</p>}
    </div>;
});
