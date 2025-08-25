import { CheckCircle, File } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { ChatMessageType } from "~/@types/chat";
import { Button, Textarea } from "~/components";
import AppAvator from "~/components/Avator";
import Markdown from "~/components/Chat/Messages/Content/Markdown";
import { downloadFile } from "~/utils";
import { emitAreaTextEvent, EVENT_TYPE } from "../useAreaText";

export default function MessageBsChoose({ type = 'choose', logo, data }: { type?: string, logo: React.ReactNode, data: ChatMessageType }) {
    const [selected, setSelected] = useState(data.message.hisValue || '')
    const handleSelect = (obj) => {
        if (selected) return

        emitAreaTextEvent({
            action: EVENT_TYPE.MESSAGE_INPUT, data: {
                nodeId: data.message.node_id,
                message: data,
                data: {
                    [data.message.key]: obj.id
                }
            }
        })

        setSelected(obj.id)
    }

    // download file
    const handleDownloadFile = (file) => {
        downloadFile(file.path, file.name)
    }

    // input
    const textRef = useRef(null)
    const [inputSended, setInputSended] = useState(!!data.message.hisValue || false)
    const handleSend = () => {
        const val = textRef.current.value
        if (!val.trim()) return
        setInputSended(true)
        emitAreaTextEvent({
            action: EVENT_TYPE.MESSAGE_INPUT, data: {
                nodeId: data.message.node_id,
                message: data,
                data: {
                    [data.message.key]: val
                }
            }
        })
    }

    const files = useMemo(() => {
        return typeof data.files === 'string' ? [] : data.files
    }, [data.files])

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
                    {logo}
                    <div className="text-sm max-w-[calc(100%-24px)]">
                        {/* message */}
                        <div><Markdown content={data.message.msg} isLatestMessage={false} webContent={undefined} /></div>
                        {/* files */}
                        <div>
                            {files.map((file) => <div
                                className="flex gap-2 w-52 border border-gray-200 shadow-sm bg-gray-50 dark:bg-gray-600 px-4 py-2 rounded-sm cursor-pointer"
                                onClick={() => handleDownloadFile(file)}
                            >
                                <div className="flex items-center"><File size={14} /></div>
                                <div>
                                    <h1 className="text-sm font-bold">{file.name}</h1>
                                    <p className="text-xs text-gray-400 mt-1">点击下载</p>
                                </div>
                            </div>)
                            }
                        </div>
                        {/* select or input */}
                        <div className="mt-2">
                            {type === 'input' ?
                                <div>
                                    <Textarea
                                        className="w-full"
                                        ref={textRef}
                                        disabled={inputSended}
                                        defaultValue={data.message.input_msg || data.message.hisValue}
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
                                        className="min-w-56 bg-[#fff] dark:bg-background rounded-xl p-4 mt-2 hover:bg-gray-200 cursor-pointer flex justify-between items-center break-all"
                                        onClick={() => handleSelect(opt)}
                                    >
                                        {opt.label}
                                        {selected === opt.id && <CheckCircle size={20} className="min-w-5" />}
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
