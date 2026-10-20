import { PasswordInput, type InputProps } from '@bisheng/ui';
import * as React from 'react';
import { useTranslation } from 'react-i18next';

import { QuestionHint as QuestionTooltip } from '@/components/bs-comp/QuestionHint';

interface PassInputProps extends InputProps {
    inputClassName?: string;
    iconClassName?: string;
    label?: React.ReactNode;
    error?: React.ReactNode;
    tooltip?: string;
}

// Keep the labeled platform field, but let the shared password control own
// masking, selection, paste, and visibility. The value is never reconstructed
// from a string of bullets.
export const PassInput = React.forwardRef<HTMLInputElement, PassInputProps>(function PassInput(
    { className, label, error, tooltip, required, id, ...props }, ref,
) {
    const { t } = useTranslation('bs');
    return <div className={className}>
        {label && <label htmlFor={id} className="bisheng-label flex items-center gap-1 mb-2">
            {label}
            {tooltip && <QuestionTooltip content={tooltip} />}
            {required && <span className="bisheng-tip">*</span>}
        </label>}
        <PasswordInput {...props} ref={ref} id={id} required={required} aria-invalid={Boolean(error) || undefined} revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
        {error && <p className="bisheng-tip mt-1">{typeof error === 'string' ? error : t('sharedUi.required')}</p>}
    </div>;
});
