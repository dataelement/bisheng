import { Input, Textarea } from '@bisheng/ui';
// src/features/chat-config/components/FormInput.tsx

import { ReactNode, useId, useState } from "react";

export const FormInput = ({
    label,
    value,
    error,
    placeholder = "",
    maxLength,
    validate,
    type = "text",
    onChange,
    isTextarea = false,
}: {
    label: ReactNode;
    value: string | number;
    error: string;
    maxLength?: number;
    validate?: (value: string) => string;
    onChange: (value: string) => void;
    type?: string;
    placeholder?: string;
    isTextarea?: boolean;
}) => {
    const fieldId = useId();
    const [isComposing, setIsComposing] = useState(false);
    const visibleError = validate && isComposing ? "" : (validate?.(String(value)) || error);
    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const newValue = e.target.value;
        onChange(newValue);
    };

    return (
        <div className={`mb-6 ${isTextarea ? "" : "pr-96"}`}>
            {typeof label === "string" ? (
                <label htmlFor={fieldId} className="block text-lg font-bold mb-2">
                    {label}
                </label>
            ) : (
                label
            )}
            {isTextarea ? (
                <Textarea id={fieldId} value={value} placeholder={placeholder} onChange={handleChange} maxLength={maxLength} textareaClassName={"mt-3 min-h-48"} showCount />
            ) : (
                <Input id={fieldId} value={value} type={type} placeholder={placeholder} onChange={handleChange} maxLength={maxLength} onCompositionStart={() => setIsComposing(true)} onCompositionEnd={() => setIsComposing(false)} aria-invalid={Boolean(visibleError)} aria-describedby={visibleError ? `${fieldId}-error` : undefined} className={"mt-3"} showCount />
            )}
            {visibleError && <p id={`${fieldId}-error`} className="text-red-500 text-xs mt-1">{visibleError}</p>}
        </div>
    );
};
