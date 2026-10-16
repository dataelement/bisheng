// @ts-strict-ignore
import { FileIcon, getFileTypebyFileName } from "~/components/ui/icon/File/FileIcon";
import { downloadFile } from "~/utils";
import useLocalize from "~/hooks/useLocalize";
export default function ChatFile({ fileName, filePath, formatError = '' }) {

    // download file
    const handleDownloadFile = (filePath) => {
        if (filePath) {
            const path = filePath.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL)
            downloadFile(path, fileName)
        }
    }

    const t = useLocalize()
    return <div
        className="group min-w-52 relative flex items-center gap-2 border bg-white p-2 rounded-xl cursor-pointer"
        onClick={() => handleDownloadFile(filePath)}
    >
        <FileIcon loading={false} type={getFileTypebyFileName(fileName)} />
        <div className="flex-1">
            <div className="max-w-48 text-sm font-medium text-gray-700 truncate">
                {fileName}
            </div>
            <p className="text-xs text-gray-400 mt-1">{t('com_bschoose_click_to_download')}</p>
            {/* F078: the file's content does not match its format */}
            {formatError && <p className="text-xs text-danger mt-1">{t('com_agent_runtime.format_error')}</p>}
        </div>
    </div>
};
