import { FlagIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { locationContext } from "@/contexts/locationContext";
import { ChatMessageType } from "@/types/chat";
import { formatStrTime } from "@/util/utils";
import { RefreshCw, Search, SquarePen } from "lucide-react";
import { useContext } from "react";
import { useTranslation } from "react-i18next";
import { useMessageStore } from "./messageStore";

export default function MessageUser({ mark = false, useName = '', data, onMarkClick }: { data: ChatMessageType }) {
    const { t } = useTranslation()

    const { appConfig } = useContext(locationContext)
    const running = useMessageStore(state => state.running)

    const handleSearch = () => {
        window.open(appConfig.dialogQuickSearch + encodeURIComponent(msg))
    }

    const handleResend = (send) => {
        const myEvent = new CustomEvent('userResendMsgEvent', {
            detail: {
                send,
                message: data.message
            }
        });
        document.dispatchEvent(myEvent);
    }

    return <div className="flex justify-end w-full">
        <div className="w-fit group min-h-8 max-w-[90%]">
            <div className="flex justify-end items-center mb-2 gap-2">
                <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    <span className="text-slate-400 text-sm">{formatStrTime(data.update_time, 'MM 月 dd 日 HH:mm')}</span>
                </div>
                {useName && <p className="text-gray-600 text-sm">{useName}</p>}
            </div>
            <div className="rounded-2xl px-6 py-4 bg-[#EEF2FF] dark:bg-[#333A48]">
                <div className="flex gap-2 ">
                    <div className="text-[#0D1638] dark:text-[#CFD5E8] text-sm break-all whitespace-break-spaces">{data.message}</div>
                    <div className="w-6 h-6 min-w-6"><img src={__APP_ENV__.BASE_URL + '/user.png'} alt="" /></div>
                </div>
            </div>
            {/* 附加信息 */}
            {
                // 数组类型的 data通常是文件上传消息，不展示附加按钮
                mark ? <div className="flex justify-between mt-2">
                    <span></span>
                    <div className="flex gap-2 text-gray-400 cursor-pointer self-end">
                        {'question' === data.category && <Button className="h-6 text-xs group-hover:opacity-100 opacity-0" onClick={onMarkClick}>
                            <FlagIcon width={12} height={12} className="cursor-pointer" />
                            <span>{t('addSimilarQuestion')}</span>
                        </Button>}
                    </div>
                </div> : (!Array.isArray(data.message) && <div className="flex justify-between mt-2">
                    <span></span>
                    <div className="flex gap-0.5 text-gray-400 cursor-pointer self-end">
                        {!running && <SquarePen className="size-6 p-1 hover:text-gray-500" onClick={() => handleResend(false)} />}
                        {!running && <RefreshCw className="size-6 p-1 hover:text-gray-500" onClick={() => handleResend(true)} />}
                        {appConfig.dialogQuickSearch && <Search className="size-6 p-1 hover:text-gray-500" onClick={handleSearch} />}
                    </div>
                </div>)
            }
        </div>
    </div>
};
