import { RefreshCw, Search, SquarePen } from "lucide-react";
import { useMemo } from "react";
import { useRecoilState } from "recoil";
import { useLocalize } from "~/hooks";
import { formatStrTime } from "~/utils";
import { bishengConfState } from "../store/atoms";
import { emitAreaTextEvent, EVENT_TYPE } from "../useAreaText";

export default function MessageUser({ useName, data, showButton }) {
    const avatar = useMemo(() => {
        return <div className="w-6 h-6 min-w-6 text-white bg-primary rounded-full flex justify-center items-center text-xs">{useName.substring(0, 2).toUpperCase()}</div>
    }, [useName])
    const [config] = useRecoilState(bishengConfState)
    const localize = useLocalize()

    const msg = useMemo(() => {
        return typeof data.message === 'string' ? data.message : data.message[data.chatKey]
    }, [])

    const handleResend = (send) => {
        emitAreaTextEvent({
            action: EVENT_TYPE.RE_ENTER,
            autoSend: send,
            text: msg
        })
    }

    const handleSearch = () => {
        window.open(config?.dialog_quick_search + encodeURIComponent(msg))
    }

    return <div className="flex w-full">
        <div className="w-fit group min-h-8 max-w-[90%]">
            <div className="flex justify-start items-center gap-2 ml-4">
                <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    <span className="text-slate-400 text-sm">{formatStrTime(data.create_time, localize('com_message_month_day_time'))}</span>
                </div>
                {/* {useName && <p className="text-gray-600 text-sm">{useName}</p>} */}
            </div>
            <div className="rounded-2xl px-4 py-2">
                <div className="flex gap-3">
                    {avatar}
                    <div className="">
                        <p className="select-none font-semibold text-base mb-1">{useName}</p>
                        <div className="text-[#0D1638] dark:text-[#CFD5E8] text-base break-all whitespace-break-spaces">{msg}</div>
                    </div>
                </div>
            </div>
            {/* footer */}
            <div className="flex justify-between mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <span></span>
                <div className="flex gap-0.5 text-gray-400 cursor-pointer self-end">
                    {showButton && <SquarePen className="size-6 p-1 hover:text-gray-500" onClick={() => handleResend(false)} />}
                    {showButton && <RefreshCw className="size-6 p-1 hover:text-gray-500" onClick={() => handleResend(true)} />}
                    {config?.dialog_quick_search && <Search className="size-6 p-1 hover:text-gray-500" onClick={handleSearch} />}
                </div>
            </div>
        </div>
    </div>
};
