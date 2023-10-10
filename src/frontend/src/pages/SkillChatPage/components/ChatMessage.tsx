import { Bot, Copy, File, User } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { Card, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { alertContext } from "../../../contexts/alertContext";
import { CodeBlock } from "../../../modals/formModal/chatMessage/codeBlock";
import { ChatMessageType } from "../../../types/chat";

export const ChatMessage = ({ chat, onSouce }: { chat: ChatMessageType, onSouce: () => void }) => {
    const textRef = useRef(null)
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
                className="markdown prose inline-block break-words text-primary dark:prose-invert max-w-[60vw]"
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
                className="markdown prose text-gray-600 inline-block break-words max-w-[60vw]"
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
    const handleCopy = (e) => {
        const copyText = e.target.parentNode
        const range = document.createRange();
        range.selectNode(copyText);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand('copy');
        window.getSelection().removeAllRanges();
        // alert('已复制文本到剪贴板：' + copyDiv.innerText);
        setSuccessData({ title: '内容已复制' })
    }

    if (chat.isSend) return chat.files ? <>
        <div className="chat chat-end">
            <div className="chat-image avatar"><div className="w-[40px] h-[40px] rounded-full bg-sky-500 flex items-center justify-center"><User color="#fff" size={28} /></div></div>
            <Card className="my-2 w-[200px] relative">
                <CardHeader>
                    <CardTitle className="flex items-center gap-2"><File />文件</CardTitle>
                    <CardDescription>{chat.files[0]?.file_name}</CardDescription>
                </CardHeader>
                {chat.files[0].data === 'progress' && <div className=" absolute top-0 left-0 w-full h-full bg-[rgba(255,255,255,0.8)]"><span className="loading loading-spinner loading-xs mr-4 align-middle absolute left-[-24px] bottom-0"></span></div>}
                {chat.files[0].data === 'error' && <div className="flex w-4 h-4 justify-center items-center absolute left-[-24px] bottom-0 bg-red-500 text-gray-50 rounded-full">!</div>}
            </Card>
        </div>
        {!chat.files[0].data && <div className={`log border-[3px] rounded-xl whitespace-pre-wrap my-4 p-4 ${color['system']} ${border['system']}`}>文件解析中</div>}
    </> :
        <div className="chat chat-end">
            <div className="chat-image avatar"><div className="w-[40px] h-[40px] rounded-full bg-sky-500 flex items-center justify-center"><User color="#fff" size={28} /></div></div>
            <div className="chat-bubble chat-bubble-info">
                {chat.category === 'loading' && <span className="loading loading-spinner loading-xs mr-4 align-middle"></span>}
                {chat.message[chat.chatKey]}
            </div>
        </div>

    // 日志分析
    if (chat.thought) return <>
        <div className={`log border-[3px] rounded-xl whitespace-pre-wrap mt-4 p-4 relative ${color[chat.category || 'system']} ${border[chat.category || 'system']}`}>
            {logMkdown}
            {chat.category === 'report' && <Copy size={20} className=" absolute right-4 top-2 cursor-pointer" onClick={handleCopy}></Copy>}
        </div>
        {!chat.end && <span className="loading loading-ring loading-md"></span>}
        {chat.source && <div className="chat-footer py-1"><button className="btn btn-outline btn-info btn-xs" onClick={onSouce}>参考来源</button></div>}
    </>

    return <div className="chat chat-start">
        <div className="chat-image avatar"><div className="w-[40px] h-[40px] rounded-full bg-gray-600 flex items-center justify-center"><Bot color="#fff" size={28} /></div></div>
        <div ref={textRef} className="chat-bubble chat-bubble-info bg-gray-300 dark:bg-gray-600">
            {chat.message.toString() ? mkdown : <span className="loading loading-ring loading-md"></span>}
            {chat.message.toString() && !chat.end && <div className="animate-cursor absolute w-2 h-5 ml-1 bg-gray-600" style={{ left: cursor.x, top: cursor.y }}></div>}
        </div>
        {chat.source && <div className="chat-footer py-1"><button className="btn btn-outline btn-info btn-xs" onClick={onSouce}>参考来源</button></div>}
    </div>
};
