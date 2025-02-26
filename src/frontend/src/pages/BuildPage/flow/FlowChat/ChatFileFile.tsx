import { checkSassUrl } from "@/components/bs-comp/FileView";
import { WordIcon } from "@/components/bs-icons/office";
import { downloadFile } from "@/util/utils";
import { useTranslation } from "react-i18next";
export default function ChatFile({ fileName, filePath }) {
    const { t } = useTranslation()

    // download file
    const handleDownloadFile = (filePath) => {
        const map = {
            "个人因私预定指引.pdf": "https://dev.aviva-cofco.com.cn/AI-FIN/grys.pdf",
            "通信费报销标准.pdf": "https://dev.aviva-cofco.com.cn/AI-FIN/txbxbz.pdf",
            "通信费报销手册.pdf": "https://dev.aviva-cofco.com.cn/AI-FIN/txbxsc.pdf",
            "协议酒店品牌介绍.pdf": "https://dev.aviva-cofco.com.cn/AI-FIN/xyjd.pdf",
            "协议酒店品牌介绍及个人因私预订指引.pdf": "https://dev.aviva-cofco.com.cn/AI-FIN/xyjdysyd.pdf",
            "美团收货地址明细.xlsx": "https://dev.aviva-cofco.com.cn/AI-FIN/mtsh.xlsx"
        }
        const url = map[fileName] ? map[fileName] : __APP_ENV__.BASE_URL + filePath
        filePath && downloadFile(map[fileName] ? url : checkSassUrl(url), fileName)
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
