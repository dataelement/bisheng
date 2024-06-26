import { AvatarIcon } from "@/components/bs-icons/avatar";
import { LoadIcon } from "@/components/bs-icons/loading";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { ChatMessageType } from "@/types/chat";
import { copyText } from "@/utils";
import { useMemo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import MessageButtons from "./MessageButtons";
import SourceEntry from "./SourceEntry";
import { useMessageStore } from "./messageStore";

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

export default function MessageBs({ data, onUnlike = () => { }, onSource }: { data: ChatMessageType, onUnlike?: any, onSource?: any }) {
    const avatarColor = colorList[
        (data.sender?.split('').reduce((num, s) => num + s.charCodeAt(), 0) || 0) % colorList.length
    ]

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

                            children[0] = (children[0] as string).replace("`▍`", "▍");
                        }

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
                {data.message.toString()}
            </ReactMarkdown>
        ),
        [data.message, data.message.toString()]
    )

    const messageRef = useRef<HTMLDivElement>(null)
    const handleCopyMessage = () => {
        copyText(messageRef.current)
    }

    const chatId = useMessageStore(state => state.chatId)

    return <div className="flex w-full py-1">
        <div className="w-fit max-w-[90%]">
            {data.sender && <p className="text-gray-600 text-xs mb-2">{data.sender}</p>}
            <div className="min-h-8 px-6 py-4 rounded-2xl bg-[#F5F6F8] dark:bg-[#313336]">
                <div className="flex gap-2">
                    <div className="w-6 h-6 min-w-6 flex justify-center items-center rounded-full" style={{ background: avatarColor }} ><AvatarIcon /></div>
                    {data.message.toString() ?
                        <div ref={messageRef} className="text-sm max-w-[calc(100%-24px)]">
                            {mkdown}
                            {/* @user */}
                            {data.receiver && <p className="text-blue-500 text-sm">@ {data.receiver.user_name}</p>}
                            {/* 光标 */}
                            {/* {data.message.toString() && !data.end && <div className="animate-cursor absolute w-2 h-5 ml-1 bg-gray-600" style={{ left: cursor.x, top: cursor.y }}></div>} */}
                        </div>
                        : <div><LoadIcon className="text-gray-400" /></div>
                    }
                </div>
            </div>
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
