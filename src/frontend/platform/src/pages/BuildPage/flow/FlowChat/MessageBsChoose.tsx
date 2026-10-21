// @ts-strict-ignore
import { Button, Textarea } from '@bisheng/ui';
import { checkSassUrl } from "@/components/bs-comp/FileView";
import { Outlined } from "bisheng-icons";




import { WorkflowMessage } from "@/types/flow";
import { downloadFile } from "@/util/utils";

import { AudioPlayComponent } from "@/components/voiceFunction/audioPlayButton";
import { useLinsightConfig } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import { useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import MessageMarkDown from "./MessageMarkDown";

export default function MessageBsChoose({ type = 'choose', logo, data }: { type?: string, logo: string, data: WorkflowMessage }) {
    const { t } = useTranslation()
    const { data: linsightConfig } = useLinsightConfig();

    const [selected, setSelected] = useState(data.message.hisValue || '')
    const handleSelect = (obj) => {
        if (selected) return
        const myEvent = new CustomEvent('outputMsgEvent', {
            detail: {
                nodeId: data.message.node_id,
                message: data,
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
    const [inputSended, setInputSended] = useState(!!data.message.hisValue || false)
    const handleSend = () => {
        const val = textRef.current.value
        if (!val.trim()) return
        setInputSended(true)
        const myEvent = new CustomEvent('outputMsgEvent', {
            detail: {
                nodeId: data.message.node_id,
                message: data,
                data: {
                    [data.message.key]: val
                }
            }
        });
        document.dispatchEvent(myEvent);
    }

    const files = useMemo(() => {
        return typeof data.files === 'string' ? [] : data.files
    }, [data.files])

    // hack
    if (typeof data.files === 'string') return null

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
                        <div>{<MessageMarkDown message={data.message.msg} />}</div>
                        {/* files */}
                        <div>
                            {files.map((file) => <div
                                className="flex gap-2 w-52 border border-gray-200 shadow-sm bg-gray-50 dark:bg-gray-600 px-4 py-2 rounded-sm cursor-pointer"
                                onClick={() => handleDownloadFile(file)}
                            >
                                <div className="flex items-center"><Outlined.FileWord size={16} /></div>
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
                                    <Textarea ref={textRef} disabled={inputSended} defaultValue={data.message.input_msg || data.message.hisValue} textareaClassName={"w-full"} />
                                    <div className="flex justify-end mt-2">
                                        <Button disabled={inputSended} onClick={handleSend}>{inputSended ? t('chat.confirmed') : t('chat.confirm')}</Button>
                                    </div>
                                </div>
                                : <div>
                                    {data.message.options.map(opt => <div
                                        key={opt.id}
                                        className="min-w-56 bg-[#fff] dark:bg-background rounded-xl p-4 mt-2 hover:bg-gray-200 cursor-pointer flex justify-between items-center break-all"
                                        onClick={() => handleSelect(opt)}
                                    >
                                        {opt.label}
                                        {selected === opt.id && <Outlined.CheckCircle size={20} className="min-w-5" />}
                                    </div>)
                                    }
                                </div>
                            }
                        </div>
                    </div>
                </div>
            </div>
            <div className={`text-right group-hover:opacity-100 opacity-0`}>
                {linsightConfig?.tts_model?.id && (
                    <AudioPlayComponent
                        messageId={String(data.message.node_id)}
                        msg={data.message.msg}
                    />
                )}
            </div>
        </div>
    </div>
};
