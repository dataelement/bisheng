// @ts-strict-ignore
import { notification } from '@bisheng/ui';
import { UploadIcon } from "@/components/bs-icons";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";

import { cname } from "../utils";
import axios, { showApiError } from "@/controllers/request";
import type { ReactNode } from 'react';

interface SimpleUploadProps {
    filekey: string;
    uploadUrl: string;
    accept: string[];
    className?: string;
    icon?: ReactNode;
    preCheck?: (file: File) => unknown;
    onSuccess: (name: string, path: string) => unknown;
}

export default function SimpleUpload({ filekey, uploadUrl, accept, className = '', icon = <UploadIcon className="group-hover:text-primary" />, preCheck, onSuccess }: SimpleUploadProps) {
    const { t } = useTranslation();


    const onDrop = async (acceptedFiles) => {
        const sizeLimit = 50 * 1024 * 1024;
        const errorFile = [];
        const files = []
        acceptedFiles.forEach(file => {
            file.size < sizeLimit ?
                files.push(file) :
                errorFile.push(file.name);
        });
        errorFile.length && notification.open({ title: String(t('prompt') ?? ''), description: (errorFile.map(str => `${t('code.file')}: ${str} ${t('code.sizeExceedsLimit')}`)).filter(Boolean).join('\n') });
        if (!files.length) return

        // Perform pre-verification (if the preCheck function is provided)
        if (preCheck) {
            try {
                const checkResult = await preCheck(files[0]);
                if (checkResult && typeof checkResult === 'object' && 'valid' in checkResult && checkResult.valid === false) {
                    const message = 'message' in checkResult ? checkResult.message : undefined;
                    notification.open({ title: String(t('prompt') ?? ''), description: typeof message === 'string' && message.trim() ? message : String(t('code.preCheckFailed')) });
                    return;
                }
            } catch (error) {
                showApiError(error);
                return;
            }
        }

        const formData = new FormData();
        formData.append(filekey, files[0]);

        try {
            const res = await axios.post(uploadUrl, formData);
            await onSuccess(files[0].name, res.file_path)
        } catch (error) {
            showApiError(error);
        }
    }

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        accept: {
            'application/*': accept.map(str => `.${str}`)
        },
        multiple: false,
        useFsAccessApi: false,
        onDrop
    });


    return <div {...getRootProps()} className={cname('group h-[100px] border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary', className)}>
        <input {...getInputProps()} />
        {icon}
        {isDragActive ? <p className="text-gray-400 text-sm">{t('code.dropFileHere')}</p> : <p className="text-gray-400 text-sm">{t('code.clickOrDragHere')}</p>}
    </div>
};
