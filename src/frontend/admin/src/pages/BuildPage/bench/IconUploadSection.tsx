// src/features/chat-config/components/IconUploadSection.tsx
import Avator from "@/components/bs-ui/input/avator";
import { Label } from "@/components/bs-ui/label";
import { uploadFileWithProgress } from "@/modals/UploadModal/upload";
import imageCompression from 'browser-image-compression';
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
    onUpload: (url: string) => void;
}) => {

    const handleFileChange = async (file: File | null) => {
        if (!file) return onUpload('');
        const options = {
            maxSizeMB: 300,          // 最大文件大小 (MB)
            maxWidthOrHeight: 300, // 最大宽度/高度
            useWebWorker: false,     // 使用 WebWorker 加速
            fileType: 'image/jpeg', // 输出格式 (可选)
        };

        try {
            const compressedBlob = await imageCompression(file, options);
            const compressedFile = new File(
                [compressedBlob],
                file.name,
                { type: file.type }
            );
            uploadFileWithProgress(compressedFile, (progress) => { }, 'icon', '').then(res => {
                onUpload(res.file_path)
            });
        } catch (error) {
            console.error('压缩失败:', error);
            return file; // 失败时返回原文件
        }
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