// @ts-strict-ignore
import { Outlined } from "bisheng-icons";
// src/features/chat-config/components/IconUploadSection.tsx





import Avator from "@/components/bs-ui/input/avator";
import { Label } from "@/components/bs-ui/label";
import { uploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { withBrandBaseUrl } from "@/utils/brand";
import Compressor from "compressorjs";
import { useState } from "react";

const MaxFileSize = 999 * 1024 * 1024; // 999MB
interface IconUploadSectionProps {
  label: string;
  enabled: boolean;
  image: string;
  onToggle: (enabled: boolean) => void;
  onUpload: (url: string, relative_path?: string) => void;
}

export function IconUploadSection({ label, image, onUpload }: IconUploadSectionProps) {
  const [uploading, setUploading] = useState(false);
  const handleFileChange = async (file: File | null) => {
    if (!file) return onUpload("");
    setUploading(true);
    try {
      const uploaded = await captureAndAlertRequestErrorHoc(
        new Promise<Blob>((resolve, reject) => {
          new Compressor(file, {
            quality: 0.6,
            maxWidth: 300,
            maxHeight: 300,
            success: resolve,
            error: reject,
          });
        }).then((result) => {
          const data = new FormData();
          data.append("file", new File([result], file.name, { type: result.type }));
          return uploadLibFile(data, {}, "icon", undefined);
        }),
      );
      if (uploaded) onUpload(uploaded.file_path, uploaded.relative_path);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-4">
        <Label className="bisheng-label">{label}</Label>
      </div>
      <Avator
        value={withBrandBaseUrl(image)}
        disabled={uploading}
        label={label}
        size={MaxFileSize}
        close
        className="mt-3"
        onChange={handleFileChange}
        accept="image/png,image/jpeg"
      >
        <div className="size-28 rounded-sm border flex items-center justify-center">
          <Outlined.Plus />
        </div>
      </Avator>
    </div>
  );
}
