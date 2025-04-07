import { checkSassUrl } from "@/components/bs-comp/FileView";
import { WordIcon } from "@/components/bs-icons/office";
import { downloadFile } from "@/util/utils";
import { useTranslation } from "react-i18next";
export default function ChatFile({ fileName, filePath }) {
    const { t } = useTranslation()

    // download file
    const handleDownloadFile = (filePath) => {
        filePath && downloadFile(checkSassUrl(filePath), fileName)
    }

    return <div
        className="flex gap-2 w-52 mb-2 ml-2 border border-gray-200 shadow-sm bg-gray-50 dark:bg-gray-600 px-4 py-2 rounded-sm cursor-pointer"
        onClick={() => handleDownloadFile(filePath)}
    >
        <div className="flex items-center"><WordIcon /></div>
        <div>
            <h1 className="text-sm font-bold">{fileName}</h1>
            <p className="text-xs text-gray-400 mt-1">{t('chat.clickDownload')}</p>
        </div>
    </div>
};
