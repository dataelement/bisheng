import MessageButtons from "@/components/bs-comp/chatComponent/MessageButtons";
import SourceEntry from "@/components/bs-comp/chatComponent/SourceEntry";
import { AvatarIcon } from "@/components/bs-icons/avatar";
import { LoadIcon, LoadingIcon } from "@/components/bs-icons/loading";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { WorkflowMessage } from "@/types/flow";
import { bindQuillEvent, formatStrTime } from "@/util/utils";
import { copyText } from "@/utils";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import ChatFile from "./ChatFileFile";
import { useMessageStore } from "./messageStore";
import { ChevronDown, ShieldAlert } from "lucide-react";
import { cname } from "@/components/bs-ui/utils";
import { ToastIcon } from "@/components/bs-icons";
import { Badge } from "@/components/bs-ui/badge";
import { TitleLogo } from "@/components/bs-comp/cardComponent";
import MsgVNodeCom from "@/pages/OperationPage/useAppLog/MsgBox";
import { SourceType } from "@/constants";
import RichText from "@/components/bs-comp/richText";

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

const ReasoningLog = ({ loading, msg = '' }) => {
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
export default function MessageBs({operation, audit, mark = false, logo, data, onUnlike = () => { }, onSource, disableBtn = false, onMarkClick, flow }: { logo: string, data: WorkflowMessage, onUnlike?: any, onSource?: any }) {
    const avatarColor = colorList[
        (data.sender?.split('').reduce((num, s) => num + s.charCodeAt(), 0) || 0) % colorList.length
    ]
    const message = useMemo(() => {
        const msg = typeof data.message === 'string' ? data.message : data.message.msg;
        return msg
            .replaceAll('$$', '$') // latex
            .replaceAll(/(\n\s{4,})/g, '\n   ') // 禁止4空格转代码
            .replace(/(?<![\n\|])\n(?!\n)/g, '\n\n') // 单个换行符
    }, [data.message])

    const mkdown = useMemo(
        () => (
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeMathjax]}
                linkTarget="_blank"
                className="bs-mkdown inline-block break-all max-w-full text-sm text-text-answer "
                components={{
                    code: ({ node, inline, className, children, ...props }) => {
                        if (children.length) {
                            if (children[0] === "▍") {
                                return (<span className="form-modal-markdown-span"> ▍ </span>);
                            }
                            if (typeof children[0] === "string") {
                                children[0] = children[0].replace("▍", "▍");
                            }
                        }
                        // className 区分代码语言 python json js 
                        const match = /language-(\w+)/.exec(className || "");

                        return !inline ? (
                            <CodeBlock
                                key={Math.random()}
                                language={(match && match[1]) || ""}
                                value={String(children).replace(/\n$/, "")}
                                {...props}
                            />
                        ) : (
                            <code className={className} {...props}> {children} </code>
                        );
                    },
                }}
            >
                {message}
            </ReactMarkdown>
        ),
        [message]
    )
    // 输出富文本
    const richText = useMemo(
        () => {
            // 命中QA了 说明返回的大概率是富文本
            if (data.source === SourceType.HAS_QA && /<[a-z][\s\S]*>/i.test(message)) {
                return <RichText msg={message}/>;
            }
            return '';
        },
        [message]
    )

    const messageRef = useRef<HTMLDivElement>(null)
    const handleCopyMessage = () => {
        // api data.id
        copyText(messageRef.current)
    }
    const chatId = useMessageStore(state => state.chatId)
    return <div className="flex w-full">
        <div className="w-fit group max-w-[90%]">
            <ReasoningLog loading={!data.end && data.reasoning_log} msg={data.reasoning_log} />
            {!(data.reasoning_log && !message && !data.files.length) && <>
                <div className="flex justify-between items-center mb-1">
                    {data.sender ? <p className="text-gray-600 text-xs">{data.sender}</p> : <p />}
                    <div className={`text-right group-hover:opacity-100 opacity-0`}>
                        <span className="text-slate-400 text-sm">{formatStrTime(data.update_time, 'MM 月 dd 日 HH:mm')}</span>
                    </div>
                </div>
                {/* 只有审计展示违规 */}
                {audit && data.review_status === 3 && <Badge variant="destructive" className="bg-red-500"><ShieldAlert className="size-4" /> 违规情况: {data.review_reason}</Badge>}
                <div className="min-h-8 px-6 py-4 rounded-2xl bg-[#F5F6F8] dark:bg-[#313336]">
                    <div className="flex gap-2">
                        {<TitleLogo url={flow?.logo} className="max-w-6 min-w-6 max-h-6 rounded-full overflow-hidden" id={flow?.id}></TitleLogo>}
                        {/* {logo ? <div className="max-w-6 min-w-6 max-h-6 rounded-full overflow-hidden">
                            <img className="w-6 h-6" src={logo} />
                        </div>
                            : <div className="w-6 h-6 min-w-6 flex justify-center items-center rounded-full" style={{ background: avatarColor }} >
                                <AvatarIcon />
                            </div>} */}
                        {message || data.files.length ?
                            <div ref={messageRef} className="text-sm max-w-[calc(100%-24px)]">
                                {message && (richText || mkdown)}
                                {data.files.length > 0 && data.files.map(file => <ChatFile key={file.path} fileName={file.name} filePath={file.path} />)}
                                {/* @user */}
                                {data.receiver && <p className="text-blue-500 text-sm">@ {data.receiver.user_name}</p>}
                                {/* 光标 */}
                                {/* {data.message.toString() && !data.end && <div className="animate-cursor absolute w-2 h-5 ml-1 bg-gray-600" style={{ left: cursor.x, top: cursor.y }}></div>} */}
                            </div>
                            : <div>{
                                !data.end && <LoadingIcon className="size-6 text-primary" />
                            }</div>
                        }
                    </div>
                </div>
            </>}
            {/* 附加信息 */}
            {
                data.end && <div className="flex justify-between mt-2">
                    <SourceEntry
                        extra={data.extra || {}}
                        end={data.end}
                        source={data.source}
                        className="pl-4"
                        onSource={() => onSource?.({
                            chatId,
                            messageId: data.id || data.message_id,
                            message,
                        })}
                    />
                    {!disableBtn && <MessageButtons
                        onlyRead={(audit || operation)}
                        mark={mark}
                        id={data.id || data.message_id}
                        data={data.liked}
                        // 审计 & 运营页面展示差评
                        msgVNode={(audit || operation) && data.remark && <MsgVNodeCom message={data.remark} />}
                        onUnlike={onUnlike}
                        onCopy={handleCopyMessage}
                        onMarkClick={onMarkClick}
                    ></MessageButtons>}
                </div>
            }
        </div>
    </div>
};
