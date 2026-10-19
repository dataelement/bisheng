import * as React from 'react';
import { Input as SharedInput, PasswordInput as SharedPasswordInput, SearchInput as SharedSearchInput, Textarea as SharedTextarea } from '@bisheng/ui';
import type { InputProps as SharedInputProps } from '@bisheng/ui';
import { Eye, EyeOff, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cname } from '../utils';

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> {
    size?: SharedInputProps['size'] | number;
    boxClassName?: string;
    showCount?: boolean;
}

// Shared fields use a soft limit. Existing platform forms still require a hard
// native limit, installed on the real element while preserving the caller's ref.
function useFieldRef<T extends HTMLInputElement | HTMLTextAreaElement>(ref: React.ForwardedRef<T>, maxLength?: number) {
    return React.useCallback((node: T | null) => {
        if (node) {
            if (maxLength === undefined) node.removeAttribute('maxlength');
            else node.maxLength = maxLength;
        }
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
    }, [ref, maxLength]);
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
    { className, boxClassName, type, size, maxLength, value, defaultValue, onChange, onPaste, ...props }, ref,
) {
    const fieldRef = useFieldRef(ref, maxLength);
    const [text, setText] = React.useState(value ?? defaultValue ?? '');
    const controlled = value !== undefined;
    const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const next = event.target.value;
        if (type === 'number') {
            const minimum = props.min === undefined ? NaN : Number(props.min);
            if (next.includes('-') || (minimum >= 1 && next === '0') ||
                (maxLength !== undefined && next.length > maxLength) ||
                (props.max !== undefined && next !== '' && Number(next) > Number(props.max))) {
                event.target.value = String(controlled ? value : text);
                return;
            }
        }
        setText(next);
        onChange?.(event);
    };
    return <SharedInput {...props} ref={fieldRef} type={type} size={typeof size === 'number' ? undefined : size}
        className={cname(boxClassName, className)}
        value={value} defaultValue={defaultValue} onChange={handleChange} maxLength={maxLength}
        onPaste={(event) => {
            if (type === 'number' && event.clipboardData.getData('text/plain').includes('-')) event.preventDefault();
            onPaste?.(event);
        }} />;
});

interface DecoratedInputProps extends InputProps {
    inputClassName?: string;
    iconClassName?: string;
}

export const SearchInput = React.forwardRef<HTMLInputElement, DecoratedInputProps>(function SearchInput(
    { className, inputClassName, iconClassName, boxClassName, type: _type, size, maxLength, ...props }, ref,
) {
    void _type;
    const fieldRef = useFieldRef(ref, maxLength);
    return <SharedSearchInput {...props} ref={fieldRef} maxLength={maxLength} size={typeof size === 'number' ? undefined : size}
        className={cname(boxClassName, className, inputClassName)} allowClear={false}
        prefixIcon={iconClassName ? <Search className={iconClassName} /> : undefined} />;
});

export const PasswordInput = React.forwardRef<HTMLInputElement, DecoratedInputProps>(function PasswordInput(
    { className, inputClassName, iconClassName, boxClassName, type: _type, size, maxLength, ...props }, ref,
) {
    void _type;
    const { t } = useTranslation('bs');
    const fieldRef = useFieldRef(ref, maxLength);
    return <SharedPasswordInput {...props} ref={fieldRef} maxLength={maxLength} size={typeof size === 'number' ? undefined : size}
        className={cname(boxClassName, className, inputClassName)}
        revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')}
        revealIcon={iconClassName ? <Eye className={iconClassName} /> : undefined}
        hideIcon={iconClassName ? <EyeOff className={iconClassName} /> : undefined} />;
});

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
    boxClassName?: string;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
    { className, boxClassName, maxLength, ...props }, ref,
) {
    const fieldRef = useFieldRef(ref, maxLength);
    return <SharedTextarea {...props} ref={fieldRef} className={boxClassName}
        textareaClassName={className}
        borderless={/(?:^|\s)border-(?:none|0)(?:\s|$)/.test(className ?? '')}
        maxLength={maxLength} showCount={maxLength !== undefined} />;
});

export { PassInput } from './PassInput';
export { InputList } from './InputList';
export { NonNegativeInput } from './NonNegativeInput';
