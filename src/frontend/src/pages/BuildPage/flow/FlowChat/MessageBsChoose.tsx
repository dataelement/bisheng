import { checkSassUrl } from "@/components/bs-comp/FileView";
import { WordIcon } from "@/components/bs-icons";
import { AvatarIcon } from "@/components/bs-icons/avatar";
import { Button } from "@/components/bs-ui/button";
import { Textarea } from "@/components/bs-ui/input";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { WorkflowMessage } from "@/types/flow";
import { downloadFile } from "@/util/utils";
import { CheckCircle } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
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

export default function MessageBsChoose({ type = 'choose', logo, data }: { type?: string, logo: string, data: WorkflowMessage }) {
    const { t } = useTranslation()
    const avatarColor = colorList[
        (data.sender?.split('').reduce((num, s) => num + s.charCodeAt(), 0) || 0) % colorList.length
    ]

    const [selected, setSelected] = useState('')
    const handleSelect = (obj) => {
        if (selected) return
        const myEvent = new CustomEvent('outputMsgEvent', {
            detail: {
                nodeId: data.message.node_id,
                data: {
                    [data.message.key]: obj.id
                }
            }
        });
        document.dispatchEvent(myEvent);
        setSelected(obj.id)
    }

    // download file
    const handleDownloadFile = (file) => {
        downloadFile(checkSassUrl(file.path), file.name)
    }

    // input
    const textRef = useRef(null)
    const [inputSended, setInputSended] = useState(false)
    const handleSend = () => {
        const val = textRef.current.value
        if (!val.trim()) return
        setInputSended(true)
        const myEvent = new CustomEvent('outputMsgEvent', {
            detail: {
                nodeId: data.message.node_id,
                data: {
                    [data.message.key]: val
                }
            }
        });
        document.dispatchEvent(myEvent);
    }

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
                {data.message.msg}
            </ReactMarkdown>
        ),
        [data.message]
    )

    return <div className="flex w-full">
        <div className="w-fit group max-w-[90%]">
            <div className="flex justify-between items-center mb-1">
                {data.sender ? <p className="text-gray-600 text-xs">{data.sender}</p> : <p />}
                <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    {/* <span className="text-slate-400 text-sm">{formatStrTime(data.update_time, 'MM 月 dd 日 HH:mm')}</span> */}
                </div>
            </div>
            <div className="min-h-8 px-6 py-4 rounded-2xl bg-[#F5F6F8] dark:bg-[#313336]">
                <div className="flex gap-2">
                    {logo ? <div className="max-w-6 min-w-6 max-h-6 rounded-full overflow-hidden">
                        <img className="w-6 h-6" src={logo} />
                    </div>
                        : <div className="w-6 h-6 min-w-6 flex justify-center items-center rounded-full" style={{ background: avatarColor }} >
                            <AvatarIcon />
                        </div>}
                    <div className="text-sm max-w-[calc(100%-24px)]">
                        {/* message */}
                        <div>{mkdown}</div>
                        {/* files */}
                        <div>
                            {data.files?.map((file) => <div
                                className="flex gap-2 w-52 border border-gray-200 shadow-sm bg-gray-50 dark:bg-gray-600 px-4 py-2 rounded-sm cursor-pointer"
                                onClick={() => handleDownloadFile(file)}
                            >
                                <div className="flex items-center"><WordIcon /></div>
                                <div>
                                    <h1 className="text-sm font-bold">{file.name}</h1>
                                    <p className="text-xs text-gray-400 mt-1">{t('chat.clickDownload')}</p>
                                </div>
                            </div>)
                            }
                        </div>
                        {/* select or input */}
                        <div className="mt-2">
                            {type === 'input' ?
                                <div>
                                    <Textarea
                                        ref={textRef}
                                        disabled={inputSended}
                                        defaultValue={data.message.input_msg}
                                    />
                                    <div className="flex justify-end mt-2">
                                        <Button
                                            className="h-8"
                                            disabled={inputSended}
                                            onClick={handleSend}
                                        >{inputSended ? '已确认' : '确认'}</Button>
                                    </div>
                                </div>
                                : <div>
                                    {data.message.options.map(opt => <div
                                        key={opt.id}
                                        className="min-w-56 bg-[#fff] rounded-xl p-4 mt-2 hover:bg-gray-200 cursor-pointer flex justify-between"
                                        onClick={() => handleSelect(opt)}
                                    >
                                        {opt.label}
                                        {selected === opt.id && <CheckCircle size={20} />}
                                    </div>)
                                    }
                                </div>
                            }
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
};
