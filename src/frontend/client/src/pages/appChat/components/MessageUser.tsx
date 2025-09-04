import { useMemo } from "react";
import { formatStrTime } from "~/utils";

export default function MessageUser({ useName, data }) {
    const avatar = useMemo(() => {
        return <div className="w-6 h-6 min-w-6 text-white bg-primary rounded-full flex justify-center items-center text-xs">{useName.substring(0, 2).toUpperCase()}</div>
    }, [useName])

    return <div className="flex w-full">
        <div className="w-fit group min-h-8 max-w-[90%]">
            <div className="flex justify-end items-center mb-2 gap-2">
                <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    <span className="text-slate-400 text-sm">{formatStrTime(data.create_time, 'MM 月 dd 日 HH:mm')}</span>
                </div>
                {/* {useName && <p className="text-gray-600 text-sm">{useName}</p>} */}
            </div>
            <div className="rounded-2xl px-6 py-4 bg-[#EEF2FF] dark:bg-[#333A48]">
                <div className="flex gap-2 ">
                    {avatar}
                    <div className="text-[#0D1638] dark:text-[#CFD5E8] text-sm break-all whitespace-break-spaces">{typeof data.message === 'string' ? data.message : data.message[data.chatKey]}</div>
                </div>
            </div>
        </div>
    </div>
};
