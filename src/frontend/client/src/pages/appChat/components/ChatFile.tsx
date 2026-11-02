import { FileIcon, getFileTypebyFileName } from "~/components/ui/icon/File/FileIcon";
import { downloadFile } from "~/utils";
import useLocalize from "~/hooks/useLocalize";
import { resolveKnowledgePreviewUrl } from "~/pages/knowledge/FilePreview/previewUrlUtils";

interface ChatFileProps {
    fileName: string;
    filePath?: string;
}

export function ChatFile({ fileName, filePath }: ChatFileProps) {
    const handleDownloadFile = () => {
        if (filePath) {
            // Object storage uses the origin bucket proxy, independently of the SPA base.
            void downloadFile(resolveKnowledgePreviewUrl(filePath), fileName);
        }
    };

    const t = useLocalize()
    return <div
        className="group min-w-52 relative flex items-center gap-2 border bg-white p-2 rounded-xl cursor-pointer"
        onClick={handleDownloadFile}
    >
        <FileIcon loading={false} type={getFileTypebyFileName(fileName) || "txt"} />
        <div className="flex-1">
            <div className="max-w-48 text-sm font-medium text-gray-700 truncate">
                {fileName}
            </div>
            <p className="text-xs text-gray-400 mt-1">{t('com_bschoose_click_to_download')}</p>
        </div>
    </div>
};
