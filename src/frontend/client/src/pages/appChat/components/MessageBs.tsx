import { CheckIcon, ChevronDown, Loader2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { ChatMessageType } from "~/@types/chat";
import Markdown from "~/components/Chat/Messages/Content/Markdown";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { cn, copyText, formatStrTime } from "~/utils";
import ChatFile from "./ChatFile";
import MessageButtons from "./MessageButtons";
import MessageSource from "./MessageSource";


export const ReasoningLog = ({ loading, msg = '' }) => {
    const [open, setOpen] = useState(true)

    if (!msg) return null

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer" onClick={() => setOpen(!open)}>
                {loading ? <div className="flex items-center font-bold gap-2 text-sm">
                    <Loader2 className="text-primary duration-300" />
                    <span>思考中</span>
                </div>
                    : <div className="flex items-center font-bold gap-2 text-sm">
                        <div className="w-5 h-5 bg-[#05B353] rounded-full p-1" >
                            <CheckIcon size={14} className='text-white' />
                        </div>
                        <span>已深度思考</span>
                    </div>
                }
                <ChevronDown className={open && 'rotate-180'} />
            </div>
            <div className={cn('bg-[#F5F6F8] dark:bg-[#313336] px-4 py-2 overflow-hidden text-sm ', open ? 'h-auto' : 'h-0 p-0')}>
                {msg.split('\n').map((line, index) => (
                    <p className="text-md mb-1 text-muted-foreground" key={index}>{line}</p>
                ))}
            </div>
        </div>
    </div>
}


export default function MessageBs({ logo, title, data, onUnlike = () => { }, onSource }:
    { logo: React.ReactNode, title: string, data: ChatMessageType, onUnlike?: any, onSource?: any }) {

    const [message, reasoningLog] = useMemo(() => {
        const msg = typeof data.message === 'string' ? data.message : data.message.msg
        const regex = /<think>(.*?)<\/think>/s;
        const match = msg.match(regex);
        if (match) {
            const outsideContent = msg.replace(regex, ''); // 标签外内容（移除标签及内部）
            const insideContent = match[1]; // 标签内内容
            return [outsideContent, insideContent]
        }
        return [msg, '']
    }, [data.message])

    const messageRef = useRef<HTMLDivElement>(null)
    const handleCopyMessage = () => {
        copyText(messageRef.current)
    }

    return <div className="flex w-full">
        <div className="w-fit group max-w-[90%]">
            <ReasoningLog loading={!data.end && (data.reasoning_log || reasoningLog)} msg={data.reasoning_log || reasoningLog} />
            {!(data.reasoning_log && !message && !data.files.length) && <>
                <div className="flex justify-between items-center mb-1">
                    {data.sender ? <p className="text-gray-600 text-xs">{data.sender}</p> : <p />}
                    <div className={`text-right group-hover:opacity-100 opacity-0`}>
                        <span className="text-slate-400 text-sm">{formatStrTime(data.create_time, 'MM 月 dd 日 HH:mm')}</span>
                    </div>
                </div>
                <div className="min-h-8 px-4 py-2 rounded-2xl">
                    <div className="flex gap-3">
                        {logo}
                        <div className="">
                            <p className="select-none font-semibold text-base mb-1">{title}</p>
                            {message || data.files.length ?
                                <div ref={messageRef} className="">
                                    {message && <div className="bs-mkdown text-base"><Markdown content={message} isLatestMessage={false} webContent={undefined} /></div>}
                                    {data.files.length > 0 && data.files.map(file => <ChatFile key={file.path} fileName={file.name} filePath={file.path} />)}
                                    {/* @user */}
                                    {data.receiver && <p className="text-blue-500 text-sm">@ {data.receiver.user_name}</p>}
                                </div>
                                : <div>{
                                    !data.end && <LoadingIcon className="size-6 text-primary" />
                                }</div>
                            }
                        </div>
                    </div>
                </div>
            </>}
            {/* 附加信息 */}
            {
                data.end && <div className="flex justify-between mt-2">
                    <MessageSource
                        extra={data.extra || {}}
                        end={data.end}
                        source={data.source}
                        className="pl-4"
                        onSource={() => onSource?.({
                            messageId: data.id,
                            message,
                        })}
                    />
                    <MessageButtons
                        id={data.id}
                        data={data.liked}
                        onUnlike={onUnlike}
                        onCopy={handleCopyMessage}
                    ></MessageButtons>
                </div>
            }
        </div>
    </div>
};
