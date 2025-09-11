import { CheckIcon, File } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { ChatMessageType } from "~/@types/chat";
import { Button, Textarea } from "~/components";
import Markdown from "~/components/Chat/Messages/Content/Markdown";
import { downloadFile } from "~/utils";
import { emitAreaTextEvent, EVENT_TYPE } from "../useAreaText";
import { changeMinioUrl } from "./ResouceModal";

export default function MessageBsChoose({ type = 'choose', logo, data, flow }: { type?: string, logo: React.ReactNode, data: ChatMessageType }) {
    const [selected, setSelected] = useState(data.message.hisValue || '')
    const handleSelect = (obj) => {
        if (selected) return
        emitAreaTextEvent({
            action: EVENT_TYPE.MESSAGE_INPUT, data: {
                nodeId: data.message.node_id,
                message: JSON.stringify({
                    ...data.message,
                    hisValue: obj.id
                }),
                msgId: data.id,
                data: {
                    [data.message.key]: obj.id
                }
            }
        })

        setSelected(obj.id)
    }

    // download file
    const handleDownloadFile = (file) => {
        downloadFile(changeMinioUrl(file.path), file.name)
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
                message: JSON.stringify({
                    ...data.message,
                    hisValue: val
                }),
                msgId: data.id,
                data: {
                    [data.message.key]: val
                }
            }
        })
    }

    const files = useMemo(() => {
        return typeof data.files === 'string' ? [] : data.files
    }, [data.files])

    return <MessageWarper flow={flow} logo={logo} >
        <div className="">
            <div className="text-base text-[#0D1638] dark:text-[#CFD5E8]">
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
                                className="min-w-56 border dark:bg-background rounded-xl p-3 mt-2 hover:bg-gray-50 cursor-pointer flex justify-between items-center break-all"
                                onClick={() => handleSelect(opt)}
                            >
                                {opt.label}
                                {selected === opt.id && <div className="size-5 bg-primary rounded-md p-1" >
                                    <CheckIcon size={14} className='text-white' />
                                </div>}
                            </div>)
                            }
                        </div>
                    }
                </div>
            </div>
        </div>
    </MessageWarper>
};


export const MessageWarper = ({ flow, logo, children }) => {
    return <div className="max-w-[600px] min-w-[384px] w-full px-4">
        <div className="flex items-center gap-3 font-medium pt-3">
            <div className="flex-shrink-0">
                {logo}
            </div>
            <span className="text-base">{flow.name}</span>
        </div>

        {/* <p className="text-sm text-gray-500 mt-2 ml-[calc(24px+0.75rem)]">
            {flow.description || '无描述信息'}
        </p> */}

        <div className="p-3 ml-6">
            {children}
        </div>
    </div>
}