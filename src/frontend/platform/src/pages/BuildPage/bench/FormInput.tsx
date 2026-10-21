import { Input, Textarea } from '@bisheng/ui';
// src/features/chat-config/components/FormInput.tsx

import { ReactNode, useId } from "react";

export const FormInput = ({
    label,
    value,
    error,
    placeholder = "",
    maxLength,
    type = "text",
    onChange,
    isTextarea = false,
}: {
    label: ReactNode;
    value: string | number;
    error: string;
    maxLength?: number;
    onChange: (value: string) => void;
    type?: string;
    placeholder?: string;
    isTextarea?: boolean;
}) => {
    const fieldId = useId();
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
                <Input id={fieldId} value={value} type={type} placeholder={placeholder} onChange={handleChange} maxLength={maxLength} className={"mt-3"} showCount />
            )}
            {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
        </div>
    );
};
