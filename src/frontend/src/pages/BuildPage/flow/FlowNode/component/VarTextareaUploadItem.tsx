import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { File, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import VarInput from "./VarInput";

export default function VarTextareaUploadItem({ nodeId, data, onChange, onValidate, onVarEvent }) {
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
    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value?.msg) {
                setError(true)
                return data.label + '不可为空'
            }
            setError(false)
            return false
        })
        return () => onValidate(() => { })
    }, [data.value])

    return (
        <div className='node-item mb-4 nodrag' data-key={data.key}>
            <Label className='bisheng-label'>{data.label}</Label>
            <VarInput
                error={error}
                placeholder={data.placeholder}
                itemKey={data.key}
                nodeId={nodeId}
                flowNode={data}
                value={data.value?.msg}
                onUpload={handleFileUpload}
                onChange={handleInputChange}
                onVarEvent={onVarEvent}
            >
                {/* Display uploaded images */}
                <div className="flex flex-wrap gap-4 p-2">
                    {
                        files.map((file, index) => (
                            // /\.(jpg|jpeg|png|gif|bmp|webp)$/i.test(file.name.toLocaleLowerCase()) ?
                            //     <div key={index} className="relative border rounded-md size-12 my-2">
                            //         <img src={file.path} alt="" className="object-cover w-12 h-12 rounded-md" />
                            //         <Button
                            //             size="icon"
                            //             variant="outline"
                            //             className="p-0 size-5 rounded-full absolute right-[-10px] top-[-10px] bg-background"
                            //             onClick={() => handleFileRemove(file.path)}
                            //         >
                            //             <X size={14} />
                            //         </Button>
                            //     </div> :
                            <div className="max-w-56 relative flex rounded-md border px-2 py-1 items-center gap-2 bg-muted">
                                <File className="min-w-5" />
                                <div className="max-w-full flex-1 pr-4">
                                    <p className="w-full font-bold truncate">{file.name}</p>
                                    {/* <span>{file.path.split('.')[1]}</span> */}
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
        input.accept = "image/*"; // Restrict to images
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
