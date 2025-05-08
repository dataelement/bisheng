// src/features/chat-config/components/IconUploadSection.tsx
import Avator from "@/components/bs-ui/input/avator";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import Compressor from "compressorjs";
import { Plus } from "lucide-react";

const MaxFileSize = 999 * 1024 * 1024; // 999MB
export const IconUploadSection = ({
    label,
    enabled,
    image,
    onToggle,
    onUpload,
}: {
    label: string;
    enabled: boolean;
    image: string;
    onToggle: (enabled: boolean) => void;
    onUpload: (url: string, relative_path?: string) => void;
}) => {

    const { toast } = useToast();

    const handleFileChange = async (file: File | null) => {
        if (!file) return onUpload('');

        new Compressor(file, {
            quality: 0.6, // 压缩质量（0-1）
            maxWidth: 300,
            maxHeight: 300,
            success(result) {
                // 压缩后的文件（result 是 Blob 类型）
                const compressedFile = new File([result], file.name, { type: result.type });
                uploadFileWithProgress(compressedFile, (progress) => { }, 'icon', '').then(res => {
                    onUpload(res.file_path, res.relative_path)
                });
            },
            error(err) {
                console.error("压缩失败:", err);
                toast({
                    title: '上传失败,请检查文件格式',
                    description: err.message,
                    variant: 'error'
                })
            },
        });
    }

    return <div>
        <div className="flex items-center gap-4">
            <Label className="bisheng-label">{label}</Label>
            {/* <Switch checked={enabled} onCheckedChange={onToggle} /> */}
        </div>
        <Avator
            value={__APP_ENV__.BASE_URL + image}
            size={MaxFileSize}
            close
            className="mt-3"
            onChange={handleFileChange}
            accept="image/png,image/jpeg"
        >
            <div className="size-28 rounded-sm border flex items-center justify-center">
                <Plus />
            </div>
        </Avator>
    </div>
};