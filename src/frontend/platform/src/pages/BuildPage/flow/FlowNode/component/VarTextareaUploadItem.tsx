import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { File, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import VarInput from "./VarInput";

export default function VarTextareaUploadItem({ nodeId, data, onChange, onValidate, onVarEvent, i18nPrefix }) {
    // console.log('data.value :>> ', data.value);
    const handleInputChange = (msg) => {
        onChange({ msg, files })
    }
    // Handle file upload
    const handleFilesChange = (updatedFiles) => {
        onChange({ msg: data.value?.msg, files: updatedFiles })
    };
    const { files, handleFileUpload, handleFileRemove } = useFileUpload(data.value?.files || [], handleFilesChange);

    const [error, setError] = useState(false)
    const { t } = useTranslation('flow')
    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value?.msg?.trim() && data.value?.files.length === 0) {
                setError(true)
                return data.label + ' ' + t('required')
            }
            setError(false)
            return false
        })
        return () => onValidate(() => { })
    }, [data.value])

    return (
        <div className='node-item mb-4 nodrag' data-key={data.key}>
            <div className="flex justify-between items-center">
                <Label className="flex items-center bisheng-label">
                    {t('messageContentVariable')}
                </Label>
                <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0]">{data.key}</Badge>
            </div>
            <VarInput
                error={error}
                placeholder={t(`${i18nPrefix}placeholder`)}
                label={t(`${i18nPrefix}label`)}
                itemKey={data.key}
                nodeId={nodeId}
                paramItem={data}
                value={data.value?.msg}
                onUpload={handleFileUpload}
                onChange={handleInputChange}
                onVarEvent={onVarEvent}
            >
                {/* Display uploaded images */}
                <div className="flex flex-wrap gap-4 p-2">
                    {
                        files.map((file) => (
                            <div className="max-w-56 relative flex rounded-md border px-2 py-1 items-center gap-2 bg-muted">
                                <File className="min-w-5" />
                                <div className="max-w-full flex-1 pr-4">
                                    <p className="w-full font-bold truncate">{file.name}</p>
                                </div>
                                <Button
                                    size="icon"
                                    variant="outline"
                                    className="p-0 size-5 rounded-full absolute right-[-10px] top-[-10px] bg-background"
                                    onClick={() => handleFileRemove(file.path)}><X size={14} /></Button>
                            </div>
                        ))
                    }
                </div>
            </VarInput>
        </div>
    );
}

export const useFileUpload = (_files, onFilesChange) => {
    const [files, setFiles] = useState(_files);
    const [loading, setLoading] = useState(false);
    const { id: flowId } = useParams();

    // Handle file upload
    const handleFileUpload = () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,text/markdown,text/html,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/msword,application/vnd.ms-powerpoint,.png,.jpg,.jpeg"; // Restrict to images
        input.style.display = "none";
        input.multiple = false;

        input.onchange = (e: Event) => {
            setLoading(true);

            const file = (e.target as HTMLInputElement).files?.[0];
            if (file) {
                uploadFileWithProgress(file, (progress) => {
                    console.log("Upload Progress:", progress);
                }, 'icon', '/api/v1/upload/workflow/' + flowId).then(res => {
                    setLoading(false);
                    const newFiles = [...files, { name: file.name, path: res.relative_path }];
                    setFiles(newFiles);
                    onFilesChange?.(newFiles);
                }).catch(err => {
                    setLoading(false);
                    console.error("Upload error:", err);
                });
            }
        };

        input.click(); // Trigger file input
    };

    // Handle file removal
    const handleFileRemove = (filePath) => {
        const newFiles = files.filter(file => file.path !== filePath);
        setFiles(newFiles);
        onFilesChange?.(newFiles);
    };

    return {
        files,
        loading,
        handleFileUpload,
        handleFileRemove,
    };
};
