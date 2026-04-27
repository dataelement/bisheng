import { LoadingIcon } from "@/components/bs-icons/loading"
import { Alert, AlertDescription } from "@/components/bs-ui/alert"
import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import ShadTooltip from "@/components/ShadTooltipComponent"
import { getChatHistoryApi } from "@/controllers/API"
import ResouceModal from "@/pages/ChatAppPage/components/ResouceModal"
import { ArrowLeft, Bot } from "lucide-react"
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

// v2.5: backend stores daily-mode `message.message` as JSON
// (`{query}` for questions, `{msg, events}` / older `{content, reasoning_content}`
// for agent answers). The admin `/chat/messages/:id` endpoint returns the raw
// column untransformed, so we normalize here to the same display string the
// client builds in parseStreamHistoryItem — plain text plus an optional
// `:::thinking\n...\n:::\n...` prefix that DailyMessageContent already renders.
function extractDisplayText(msg: any): string {
    const raw = msg?.text ?? "";
    if (typeof raw !== "string" || !raw) return "";
    const trimmed = raw.trim();
    if (!trimmed.startsWith("{")) return raw;

    let parsed: any;
    try {
        parsed = JSON.parse(trimmed);
    } catch {
        return raw;
    }
    if (!parsed || typeof parsed !== "object") return raw;

    if (msg.isCreatedByUser) {
        if (typeof parsed.query === "string") return parsed.query;
        if (typeof parsed.text === "string") return parsed.text;
        return raw;
    }

    const content =
        typeof parsed.msg === "string"
            ? parsed.msg
            : typeof parsed.content === "string"
                ? parsed.content
                : "";

    let reasoning = "";
    if (Array.isArray(parsed.events)) {
        reasoning = parsed.events
            .filter((e: any) => e && e.type === "thinking")
            .map((e: any) => (typeof e?.content === "string" ? e.content : ""))
            .filter(Boolean)
            .join("\n\n");
    } else if (Array.isArray(parsed.thinking_segments) && parsed.thinking_segments.length) {
        reasoning = parsed.thinking_segments
            .map((s: any) => (typeof s?.content === "string" ? s.content : ""))
            .filter(Boolean)
            .join("\n\n");
    } else if (typeof parsed.reasoning_content === "string") {
        reasoning = parsed.reasoning_content;
    }

    if (reasoning) return `:::thinking\n${reasoning}\n:::\n${content}`;
    return content || raw;
}

export default function DailyChatDetail() {
    const { cid } = useParams()
    const [messages, setMessages] = useState<Message[]>([])
    const [loading, setLoading] = useState(true)
    const { appConfig } = useContext(locationContext)

    const { t } = useTranslation()
    const title = messages.length > 0 ? messages[0].flow_name : ''

    useEffect(() => {
        getChatHistoryApi(cid).then((res: any) => {
            const items = Array.isArray(res) ? res : []
            const normalised = items.map((m: any) => ({ ...m, text: extractDisplayText(m) }))
            setMessages(normalised)
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
                        <span className=" text-gray-700 text-sm font-black pl-4">{t('log.detailedSession')}</span>
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
                                        <div className="w-7 h-7 rounded-full flex items-center justify-center bg-gray-100 dark:bg-zinc-800 overflow-hidden">
                                            {appConfig?.worksapceIcon
                                                ? <img src={__APP_ENV__.BASE_URL + appConfig.worksapceIcon} alt="" className="w-full h-full object-cover" />
                                                : <Bot size={16} className="text-gray-500" />}
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

