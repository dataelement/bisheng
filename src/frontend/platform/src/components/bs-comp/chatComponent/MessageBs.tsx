import { ToastIcon } from "@/components/bs-icons";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { cname } from "@/components/bs-ui/utils";
import MessageMarkDown from "@/pages/BuildPage/flow/FlowChat/MessageMarkDown";
import { ChatMessageType } from "@/types/chat";
import { formatStrTime } from "@/util/utils";
import { copyText } from "@/utils";
import { ChevronDown } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import MessageButtons from "./MessageButtons";
import SourceEntry from "./SourceEntry";
import { useMessageStore } from "./messageStore";
import { useLinsightConfig } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import { AudioPlayComponent } from "@/components/voiceFunction/audioPlayButton";


// 颜色列表
const colorList = [
    "#111",
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

export const ReasoningLog = ({ loading, msg = '' }) => {
    const [open, setOpen] = useState(true)
    // console.log('msg :>> ', msg);
    if (!msg) return null

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer" onClick={() => setOpen(!open)}>
                {loading ? <div className="flex items-center font-bold gap-2 text-sm">
                    <LoadIcon className="text-primary duration-300" />
                    <span>思考中</span>
                </div>
                    : <div className="flex items-center font-bold gap-2 text-sm">
                        <ToastIcon type="success" />
                        <span>已深度思考</span>
                    </div>
                }
                <ChevronDown className={open && 'rotate-180'} />
            </div>
            <div className={cname('bg-[#F5F6F8] dark:bg-[#313336] px-4 py-2 overflow-hidden text-sm ', open ? 'h-auto' : 'h-0 p-0')}>
                {msg.split('\n').map((line, index) => (
                    <p className="text-md mb-1 text-muted-foreground" key={index}>{line}</p>
                ))}
            </div>
        </div>
    </div>
}

export default function MessageBs({ debug, mark = false, logo, data, onUnlike = () => { }, onSource, onMarkClick, chat }: { logo: string, data: ChatMessageType, onUnlike?: any, onSource?: any }) {
    const avatarColor = colorList[
        (data.sender?.split('').reduce((num, s) => num + s.charCodeAt(), 0) || 0) % colorList.length
    ]

    const message = useMemo(() => {
        return data.message[data.chatKey] || data.message
    }, [data.message])


    const messageRef = useRef<HTMLDivElement>(null)
    const handleCopyMessage = () => {
        // api data.id
        copyText(messageRef.current)
    }
    const { data: linsightConfig, isLoading: loading, refetch: refetchConfig, error } = useLinsightConfig();

    const chatId = useMessageStore(state => state.chatId)

    return <div className="flex w-full">
        <div className="w-fit group max-w-[90%]">
            <ReasoningLog loading={!data.end && data.reasoning_log} msg={data.reasoning_log} />
            {!(data.reasoning_log && !message && !data.files.length) && <>
                <div className="flex justify-between items-center mb-1">
                    {data.sender ? <p className="text-gray-600 text-xs">{data.sender}</p> : <p />}
                    <div className={`text-right group-hover:opacity-100 opacity-0`}>
                        <span className="text-slate-400 text-sm">{formatStrTime(data.create_time, 'MM 月 dd 日 HH:mm')}</span>
                    </div>
                </div>
                <div className="min-h-8 px-6 py-4 rounded-2xl bg-[#F5F6F8] dark:bg-[#313336]">
                    <div className="flex gap-2">
                        {logo}
                        {data.message.toString() ?
                            <div ref={messageRef} className="text-sm max-w-[calc(100%-24px)]">
                                {<MessageMarkDown message={message} />}
                                {/* @user */}
                                {data.receiver && <p className="text-blue-500 text-sm">@ {data.receiver.user_name}</p>}
                                {/* 光标 */}
                                {/* {data.message.toString() && !data.end && <div className="animate-cursor absolute w-2 h-5 ml-1 bg-gray-600" style={{ left: cursor.x, top: cursor.y }}></div>} */}
                            </div>
                            : <div><LoadingIcon className="size-6 text-primary" /></div>
                        }
                    </div>
                </div>
                <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    {linsightConfig?.tts_model?.id && (
                        <AudioPlayComponent
                            messageId={String(data.id)}
                            msg={message}
                        />
                    )}
                </div>

            </>}
            {/* 附加信息 */}
            {
                !!data.id && data.end && <div className="flex justify-between mt-2">
                    <SourceEntry
                        extra={data.extra}
                        end={data.end}
                        source={data.source}
                        className="pl-4"
                        onSource={() => onSource?.({
                            chatId,
                            messageId: data.id,
                            message: data.message || data.thought,
                        })} />
                    {!debug && <MessageButtons
                        mark={mark}
                        id={data.id}
                        data={data.liked}
                        onUnlike={onUnlike}
                        onCopy={handleCopyMessage}
                        onMarkClick={onMarkClick}
                        debug={debug}
                        text={data.message || data.thought}
                    ></MessageButtons>}
                </div>
            }
        </div>
    </div>
};
