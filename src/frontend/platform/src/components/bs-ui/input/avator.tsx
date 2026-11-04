// @ts-strict-ignore
import { toast } from '@bisheng/ui';
import { Camera, X } from "lucide-react";
import type { ChangeEvent, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cname } from "../utils";

interface AvatorProps {
    size?: number;
    accept?: string;
    value?: string;
    close?: boolean;
    className?: string;
    onChange: (file: File | null) => void;
    children?: ReactNode;
    disabled?: boolean;
    label?: string;
}

export default function Avator({
    size = 5 * 1024 * 1024,
    accept = "image/jpeg,image/png",
    value,
    close = false,
    className,
    onChange,
    children,
    disabled = false,
    label = undefined,
}: AvatorProps) {
    const { t } = useTranslation()

    const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (disabled) return;
        if (file) {
            const isValidSize = file.size <= size;
            const isValidType = accept.split(',').some(type => file.type === type);

            const errormgs: string[] = []
            if (!isValidSize) errormgs.push(`${t('build.fileSizeLimit')} ${size / 1024 / 1024}MB`)
            if (!isValidType) errormgs.push(`${t('build.fileTypeLimit')} ${accept}`)

            errormgs.length ? toast.show({ type: 'error', message: errormgs.filter(Boolean).join('\n') }) : onChange(file)
        }
    };

    return <div className={cname("flex w-full rounded-md gap-4", className)}>
        <div className="relative group">
            {
                value ? <img src={value} className="max-w-24 max-h-24 min-w-8 min-h-8 rounded-md object-cover border" alt="" /> : children
            }
            <div className="absolute left-0 top-0 w-full h-full opacity-0 group-hover:opacity-100 transition-opacity duration-300 bg-black/50 flex items-center justify-center rounded-md">
                <input
                    className="absolute top-0 left-0 inset-0 w-full h-full opacity-0 cursor-pointer"
                    type="file"
                    accept={accept}
                    disabled={disabled}
                    aria-busy={disabled}
                    aria-label={label}
                    onChange={handleFileChange}
                />
                <Camera className="text-gray-50 w-6 h-6" />
                {close && value && <div className="absolute -top-3 -right-3 bg-gray-50 rounded-full p-1 cursor-pointer border border-gray-300" onClick={() => { if (!disabled) onChange(null); }}><X size={14} /></div>}
            </div>
        </div>
    </div>
};
