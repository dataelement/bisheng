import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import { File, X } from "lucide-react";
import { useState } from "react";
import VarInput from "./VarInput";
import useFlowStore from "../../flowStore";

export default function VarTextareaUploadItem({ nodeId, data, onChange }) {
    // console.log('data.value :>> ', data.value);
    const handleInputChange = (msg) => {
        onChange({ msg, files })
    }
    // Handle file upload
    const handleFilesChange = (updatedFiles) => {
        onChange({ msg: data.value?.msg, files: updatedFiles })
    };
    const { files, handleFileUpload, handleFileRemove } = useFileUpload(data.value?.files || [], handleFilesChange);

    return (
        <div className='node-item mb-2 nodrag' data-key={data.key}>
            <Label className='bisheng-label'>{data.label}</Label>
            <VarInput
                nodeId={nodeId}
                flowNode={data}
                value={data.value?.msg}
                onUpload={handleFileUpload}
                onChange={handleInputChange}
            >
                {/* Display uploaded images */}
                <div className="flex flex-wrap gap-4 p-2">
                    {
                        files.map((file, index) => (
                            /\.(jpg|jpeg|png|gif|bmp|webp)$/i.test(file.path) ?
                                <div key={index} className="relative border rounded-md size-12">
                                    <img src={file.path} alt="" className="object-cover w-12 h-12 rounded-md" />
                                    <Button
                                        size="icon"
                                        variant="outline"
                                        className="p-0 size-5 rounded-full absolute right-[-10px] top-[-10px] bg-background"
                                        onClick={() => handleFileRemove(file.path)}
                                    >
                                        <X size={14} />
                                    </Button>
                                </div> :
                                <div className="relative flex rounded-md border px-2 py-1 items-center gap-2 bg-muted">
                                    <File />
                                    <div>
                                        <p className="font-bold">{file.name}</p>
                                        <span>{file.path.split('.')[1]}</span>
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

    // Handle file upload
    const handleFileUpload = () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*"; // Restrict to images
        input.style.display = "none";
        input.multiple = false;

        input.onchange = (e: Event) => {
            setLoading(true);
            const flowId = 'flowid_xxxx' // TODO

            const file = (e.target as HTMLInputElement).files?.[0];
            if (file) {
                uploadFileWithProgress(file, (progress) => {
                    console.log("Upload Progress:", progress);
                }, 'icon', '/api/v1/upload/workflow/' + flowId).then(res => {
                    setLoading(false);
                    const newFiles = [...files, { name: file.name, path: res.file_path }];
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
