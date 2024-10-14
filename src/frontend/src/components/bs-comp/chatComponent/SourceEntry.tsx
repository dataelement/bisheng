import { Badge } from "@/components/bs-ui/badge";
import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";

const enum SourceType {
    /** 无溯源 */
    NONE = 0,
    /** 文件 */
    FILE = 1,
    /** 无权限 */
    NO_PERMISSION = 2,
    /** 链接s */
    LINK = 3,
    /** 已命中的QA */
    HAS_QA = 4,
}

export default function SourceEntry({ extra, end, source, className = '', onSource }) {
    const { t } = useTranslation()

    if (source === SourceType.NONE || !end) return <div className={className}></div>
    const extraObj = extra ? JSON.parse(extra) : null

    return <div className={className}>
        {(() => {
            switch (source) {
                case SourceType.FILE:
                    return <Badge className="cursor-pointer" onClick={onSource}>{t('chat.source')}</Badge>;
                case SourceType.NO_PERMISSION:
                    return <p className="flex text-xs text-gray-400 gap-1 items-center"><Info className="text-red-300" />{t('chat.noAccess')}</p>;
                case SourceType.LINK:
                    return (
                        <div className="flex flex-col text-blue-500 text-xs">
                            {
                                extraObj.doc?.map(el => <a key={el.url} href={el.url} target="_blank">{el.title}</a>)
                            }
                        </div>
                    );
                case SourceType.HAS_QA:
                    return <a href={extraObj.url} target="_blank" className="text-blue-500 text-xs">{extraObj.qa}</a>;
                default:
                    return null;
            }
        })()}
    </div>
};
