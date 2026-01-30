import { LoadingIcon } from "@/components/bs-icons/loading"
import { Alert, AlertDescription } from "@/components/bs-ui/alert"
import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import ShadTooltip from "@/components/ShadTooltipComponent"
import { getChatHistoryApi } from "@/controllers/API"
import ResouceModal from "@/pages/ChatAppPage/components/ResouceModal"
import { ArrowLeft } from "lucide-react"
import { useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { useParams } from "react-router-dom"
import { MessageContent } from "./DailyMessageContent"
import { locationContext } from "@/contexts/locationContext"

interface Message {
    messageId: string;
    sender: string;
    text: string;
    isCreatedByUser: boolean;
    user_name: string;
    source: number;
}

export default function DailyChatDetail() {
    const { cid } = useParams()
    const [messages, setMessages] = useState<Message[]>([])
    const [loading, setLoading] = useState(true)
    const { appConfig } = useContext(locationContext)

    const { t } = useTranslation()
    const title = messages.length > 0 ? messages[0].flow_name : ''

    useEffect(() => {
        getChatHistoryApi(cid).then(res => {
            setMessages(res)
            setLoading(false)
        }).catch(() => setLoading(false))
    }, [cid])

    const sourceRef = useRef(null)
    const showResouce = (msgId, msg) => {
        sourceRef.current?.openModal({
            chatId: cid,
            messageId: msgId,
            message: msg,
        })
    }

    return (
        <div>
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}

            <div className="bg-background-login px-4">
                <div className="flex justify-between items-center py-4">
                    <div className="flex items-center">
                        <ShadTooltip content={t('back')} side="top">
                            <Button
                                className="w-[36px] px-2 rounded-full"
                                variant="outline"
                                onClick={() => window.history.back()}
                            ><ArrowLeft className="side-bar-button-size" /></Button>
                        </ShadTooltip>
                        <span className=" text-gray-700 text-sm font-black pl-4">{title}</span>
                    </div>
                </div>

                {/* messages */}
                <div className="h-[calc(100vh-132px)] overflow-y-auto">
                    <div className="max-w-4xl mx-auto px-4 py-8">
                        {messages.map((msg) => (
                            <div key={msg.messageId} className="mb-8 flex items-start gap-4">
                                {/* avatar */}
                                <div className="flex-shrink-0">
                                    {msg.isCreatedByUser ? (
                                        <div className="w-7 h-7 bg-red-500 rounded-full flex items-center justify-center text-white text-xs font-bold">
                                            {msg.user_name.slice(0, 2).toLocaleUpperCase()}
                                        </div>
                                    ) : (
                                        <div className="w-7 h-7 rounded-full flex items-center justify-center text-white">
                                            <div className="">
                                                <img src={appConfig?.worksapceIcon} alt="" />
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {/* content */}
                                <div className="flex-1 overflow-hidden">
                                    <div className="font-bold text-gray-900 dark:text-zinc-100 mb-1 text-base">
                                        {msg.isCreatedByUser ? msg.user_name : msg.sender}
                                    </div>
                                    {
                                        msg.error
                                            ? <Alert className="border-red-500/20 bg-red-500/5 px-3 py-2"><AlertDescription>{msg.text}</AlertDescription></Alert>
                                            : <div className="prose prose-sm max-w-none dark:prose-invert prose-pre:bg-zinc-900 prose-pre:border prose-pre:border-zinc-700">
                                                <MessageContent text={msg.text} />

                                                {msg.source === 1 && <div className="mt-2">
                                                    <Badge className="cursor-pointer" onClick={() => showResouce(msg.messageId, msg.text)}>{t('chat.source')}</Badge>
                                                </div>}
                                            </div>
                                    }
                                    {/* <div className="max-w-none ">
                                        <MessageMarkDown message={msg.text}> </MessageMarkDown>
                                    </div> */}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            <ResouceModal ref={sourceRef}></ResouceModal>
        </div>
    )
}

