import { Bot, Copy, File, User } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { Card, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { alertContext } from "../../../contexts/alertContext";
import { CodeBlock } from "../../../modals/formModal/chatMessage/codeBlock";
import { ChatMessageType } from "../../../types/chat";
import { downloadFile } from "../../../util/utils";
import { checkSassUrl } from "./FileView";
import Thumbs from "./Thumbs";
import { Button } from "../../../components/ui/button";

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

export const ChatMessage = ({ chat, userName, onSource }: { chat: ChatMessageType, userName: string, onSource: () => void }) => {
    // const { user } = useContext(userContext);
    // console.log('chat :>> ', chat);

    const textRef = useRef(null)
    const { t } = useTranslation()
    const [cursor, setCursor] = useState({ x: 0, y: 0 })
    useEffect(() => {
        if (!textRef.current || chat.end || !chat.message) return
        const lastText = getLastTextNode(textRef.current)
        const textNode = document.createTextNode('\u200b')
        if (lastText) {
            lastText.parentNode.appendChild(textNode)
            const range = document.createRange()
            range.setStart(textNode, 0)
            range.setEnd(textNode, 0)
            const rect = range.getBoundingClientRect()
            const domRect = textRef.current.getBoundingClientRect()
            const x = rect.left - domRect.left
            const y = rect.top - domRect.top
            setCursor({ x, y })
        }
        textNode.remove()

    }, [chat.message, chat.message.toString()])

    const mkdown = useMemo(
        () => (
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeMathjax]}
                className="markdown prose inline-block break-words text-primary dark:prose-invert max-w-full text-sm"
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
                {chat.message.toString()}
            </ReactMarkdown>
        ),
        [chat.message, chat.message.toString()]
    )

    // 日志markdown
    const logMkdown = useMemo(
        () => (
            chat.thought && <ReactMarkdown
                className="markdown prose text-gray-600 inline-block break-words max-w-full text-sm"
            >
                {chat.thought.toString()}
            </ReactMarkdown>
        ),
        [chat.thought]
    )

    const getLastTextNode = (dom) => {
        const children = dom.childNodes
        for (let i = children.length - 1; i >= 0; i--) {
            const node = children[i]
            if (node.nodeType === Node.TEXT_NODE && /\S/.test(node.nodeValue)) {
                node.nodeValue = node.nodeValue.replace(/\s+$/, '')
                return node
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                const last = getLastTextNode(node)
                if (last) return last
            }
        }
        return null
    }
    const border = { system: 'border-slate-500', question: 'border-amber-500', processing: 'border-cyan-600', answer: 'border-lime-600', report: 'border-slate-500' }
    const color = { system: 'bg-slate-50', question: 'bg-slate-50', processing: 'bg-slate-50', answer: 'bg-slate-50', report: 'bg-slate-50' }

    const { setSuccessData } = useContext(alertContext);
    const handleCopy = (copyText) => {
        // const copyText = e.target.parentNode
        const range = document.createRange();
        range.selectNode(copyText);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand('copy');
        window.getSelection().removeAllRanges();
        // alert('已复制文本到剪贴板：' + copyDiv.innerText);
        setSuccessData({ title: t('chat.copyTip') })
    }

    // download file
    const handleDownloadFile = (file) => {
        const url = file?.file_url
        url && downloadFile(checkSassUrl(url), file?.file_name)
    }

    const sourceContent = (source: SourceType) => {
        const extra = chat.extra ? JSON.parse(chat.extra) : null
        const renderContent = () => {
            switch (source) {
                case SourceType.FILE:
                    return (
                        <button className="btn btn-outline btn-info btn-xs text-[rgba(53,126,249,.85)] hover:bg-transparent text-xs relative" onClick={onSource}>
                            {t('chat.source')}
                        </button>
                    );
                case SourceType.NO_PERMISSION:
                    return (
                        <p className="flex items-center text-gray-400 pb-2"><span className="w-4 h-4 bg-red-400 rounded-full flex justify-center items-center text-[#fff] mr-1">!</span>{t('chat.noAccess')}</p>
                    );
                case SourceType.LINK:
                    return <div className="flex flex-col items-start gap-0">
                        {
                            extra.doc?.map(el =>
                                <Button variant="link" size="sm" className="text-blue-500 h-6 p-0">
                                    <a href={el.url} target="_blank" className="truncate max-w-[400px]">{el.title}</a>
                                </Button>)
                        }
                    </div>;
                case SourceType.HAS_QA:
                    return <p className="flex items-center text-gray-400 pb-2">{extra.qa}</p>;
                default:
                    return null;
            }
        };

        return (
            <div className="chat-footer py-1">
                {renderContent()}
            </div>
        );
    };

    // 日志分析
    if (chat.thought) return <>
        <div className={`log border-[3px] rounded-xl whitespace-pre-wrap mt-4 p-4 relative ${color[chat.category || 'system']} ${border[chat.category || 'system']}`}>
            {logMkdown}
            {chat.category === 'report' && <Copy size={20} className=" absolute right-4 top-2 cursor-pointer" onClick={(e) => handleCopy(e.target.parentNode)}></Copy>}
        </div>
        {!chat.end && <span className="loading loading-ring loading-md"></span>}
        {chat.source !== SourceType.NONE && chat.end && sourceContent(chat.source)}
    </>

    if (chat.category === 'divider') {
        // 轮次分割线
        return <div className="divider text-gray-500 text-sm">{t('chat.roundOver')}</div>
    }


    // if (chat.isSend) return chat.files.length ? <>
    // 发送消息
    if (chat.isSend) return <div className="chat chat-end">
        <div className="chat-image avatar"><div className="w-[40px] h-[40px] rounded-full bg-[rgba(53,126,249,.6)] flex items-center justify-center"><User color="#fff" size={28} /></div></div>
        <div className="chat-header text-gray-400 text-sm">{userName}</div>
        <div className="chat-bubble chat-bubble-info bg-[rgba(53,126,249,.15)] dark:text-gray-100 whitespace-pre-line text-sm min-h-8">
            {chat.category === 'loading' && <span className="loading loading-spinner loading-xs mr-4 align-middle"></span>}
            {chat.message[chat.chatKey]}
        </div>
    </div>
    {/* 文件 */ }
    // <div className="chat chat-end">
    //     <div className="chat-image avatar"><div className="w-[40px] h-[40px] rounded-full bg-sky-500 flex items-center justify-center"><User color="#fff" size={28} /></div></div>
    //     <div className="chat-header text-gray-400 text-sm">{userName}</div>
    //     <Card className="my-2 w-[200px] relative">
    //         <CardHeader>
    //             <CardTitle className="flex items-center gap-2"><File />{t('file')}</CardTitle>
    //             <CardDescription>{decodeURIComponent(chat.files[0]?.file_name || '')}</CardDescription>
    //         </CardHeader>
    //         {chat.files[0]?.data === 'progress' && <div className=" absolute top-0 left-0 w-full h-full bg-[rgba(255,255,255,0.8)]"><span className="loading loading-spinner loading-xs mr-4 align-middle absolute left-[-24px] bottom-0"></span></div>}
    //         {chat.files[0]?.data === 'error' && <div className="flex w-4 h-4 justify-center items-center absolute left-[-24px] bottom-0 bg-red-500 text-gray-50 rounded-full">!</div>}
    //     </Card>
    // </div>
    {/* {!chat.files[0]?.data && <div className={`log border-[3px] rounded-xl whitespace-pre-wrap my-4 p-4 ${color['system']} ${border['system']}`}>{t('chat.filePrsing')}</div>} */ }
    // </> :

    const avatarColor = colorList[(chat.sender?.split('').reduce((num, s) => num + s.charCodeAt(), 0) || 0) % colorList.length]
    // 模型返回的文件
    if (chat.files.length) return <div className="chat chat-start">
        <div className="chat-image avatar">
            <div className="w-[40px] h-[40px] rounded-full flex items-center justify-center" style={{ background: avatarColor }}><Bot color="#fff" size={28} /></div>
        </div>
        {chat.sender && <div className="chat-header text-gray-400 text-sm">{chat.sender}</div>}
        <Card className={`my-2 w-[200px] relative ${chat.files[0]?.file_url && 'cursor-pointer'}`} onClick={() => handleDownloadFile(chat.files[0])}>
            <CardHeader>
                <CardTitle className="flex items-center gap-2"><File />{t('file')}</CardTitle>
                <CardDescription>{chat.files[0]?.file_name}</CardDescription>
            </CardHeader>
        </Card>
    </div>

    // 模型user
    return <div className="chat chat-start">
        <div className="chat-image avatar">
            <div className="w-[40px] h-[40px] rounded-full flex items-center justify-center" style={{ background: avatarColor }}><Bot color="#fff" size={28} /></div>
        </div>
        {chat.sender && <div className="chat-header text-gray-400 text-sm">{chat.sender}</div>}
        <div ref={textRef} className={`chat-bubble chat-bubble-info bg-[rgba(240,240,240,0.8)] dark:bg-gray-600 min-h-8 relative ${chat.id && chat.end && 'pb-8'}`}>
            {chat.message.toString() ? mkdown : <span className="loading loading-ring loading-md"></span>}
            {/* @user */}
            {chat.receiver && <p className="text-blue-500 text-sm">@ {chat.receiver.user_name}</p>}
            {/* 光标 */}
            {chat.message.toString() && !chat.end && <div className="animate-cursor absolute w-2 h-5 ml-1 bg-gray-600" style={{ left: cursor.x, top: cursor.y }}></div>}
            {/* 赞 踩 */}
            {!!chat.id && chat.end && <Thumbs
                id={chat.id}
                data={chat.liked}
                onCopy={handleCopy}
                className={`absolute w-full left-0 bottom-[8px] justify-end pr-5`}></Thumbs>
            }
        </div>
        {chat.source !== SourceType.NONE && chat.end && sourceContent(chat.source)}
    </div>
};
