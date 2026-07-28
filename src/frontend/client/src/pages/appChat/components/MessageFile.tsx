import { formatStrTime } from "~/utils"
import { AppChatFileChip } from "./AppChatFileChip"

export default function MessageFile({ data, title, logo }) {

    return <div className="flex w-full">
        <div className="w-fit group max-w-[90%]">
            <div className="flex justify-between items-center mb-1">
                {data.sender ? <p className="text-gray-600 text-xs">{data.sender}</p> : <p />}
                <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    <span className="text-slate-400 text-sm">{formatStrTime(data.create_time, 'MM 月 dd 日 HH:mm')}</span>
                </div>
            </div>
            <div className="min-h-8 px-4 py-2">
                <div className="flex gap-3">
                    {logo}
                    <div>
                        <p className="select-none font-semibold text-base mb-2">{title}</p>
                        <div className="flex flex-col gap-2">
                            {data.files.map((file, index) => (
                                <AppChatFileChip key={index} file={file} variant="message" />
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div >
};
