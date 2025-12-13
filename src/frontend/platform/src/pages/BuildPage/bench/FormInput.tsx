// src/features/chat-config/components/FormInput.tsx
import { Input, Textarea } from "@/components/bs-ui/input";
import { ReactNode } from "react";

export const FormInput = ({
    label,
    value,
    error,
    placeholder = '',
    maxLength,
    type = 'text',
    onChange,
    isTextarea = false,
}: {
    label: ReactNode;
    value: string;
    error: string;
    maxLength?: number;
    onChange: (value: string) => void;
    type?: string;
    placeholder?: string;
    isTextarea?: boolean;
}) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const newValue = e.target.value;
        if (!maxLength || newValue.length <= maxLength) {
            onChange(newValue);
        }
    };

    return (
        <div className={`mb-6 ${isTextarea ? '' : 'pr-96'}`}>
            {typeof label === 'string' ? <p className="text-lg font-bold mb-2">{label}</p> : label}
            {isTextarea ? (
                <Textarea
                    value={value}
                    placeholder={placeholder}
                    onChange={handleChange}
                    className="mt-3 min-h-48"
                    maxLength={maxLength}
                />
            ) : (
                <Input
                    value={value}
                    type={type}
                    placeholder={placeholder}
                    onChange={handleChange}
                    className="mt-3"
                    maxLength={maxLength}
                />
            )}
            {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
        </div>
    );
};