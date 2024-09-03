import { AvatarIcon } from "@/components/bs-icons/avatar";
import { WordIcon } from "@/components/bs-icons/office";
import { downloadFile } from "@/util/utils";
import { useTranslation } from "react-i18next";
import { checkSassUrl } from "../FileView";

// 颜色列表
const colorList = [
    "#666",
    "#FF5733",
    "#3498DB",
    "#27AE60",
    "#E74C3C",
    "#9B59B6",
    "#F1C40F",
    "#34495E",
    "#16A085",
    "#E67E22",
    "#95A5A6"
]

export default function FileBs({ data }) {
    const { t } = useTranslation()
    const avatarColor = colorList[(data.sender?.split('').reduce((num, s) => num + s.charCodeAt(), 0) || 0) % colorList.length]

    // download file
    const handleDownloadFile = (file) => {
        const url = file?.file_url
        url && downloadFile(checkSassUrl(url), file?.file_name)
    }

    return <div className="flex w-full py-1">
        <div className="w-fit min-h-8 rounded-2xl px-6 py-4 max-w-[90%]">
            {data.sender && <p className="text-primary text-xs mb-2" style={{ background: avatarColor }}>{data.sender}</p>}
            <div className="flex gap-2 ">
                <div className="w-6 h-6 min-w-6 flex justify-center items-center rounded-full" style={{ background: avatarColor }} ><AvatarIcon /></div>
                <div
                    className="flex gap-2 w-52 border border-gray-200 shadow-sm bg-gray-50 dark:bg-gray-600 px-4 py-2 rounded-sm cursor-pointer"
                    onClick={() => handleDownloadFile(data.files[0])}
                >
                    <div className="flex items-center"><WordIcon /></div>
                    <div>
                        <h1 className="text-sm font-bold">{data.files[0]?.file_name}</h1>
                        <p className="text-xs text-gray-400 mt-1">{t('chat.clickDownload')}</p>
                    </div>
                </div>
            </div>
        </div>
    </div>
};
