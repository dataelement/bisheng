// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import { LoadingIcon } from "@/components/bs-icons/loading"
import { Alert, AlertDescription } from "@/components/bs-ui/alert"

import { Tooltip } from "@bisheng/ui"
import { Outlined } from "bisheng-icons"
import { getChatHistoryApi } from "@/controllers/API"
import ResouceModal from "@/pages/ChatAppPage/components/ResouceModal"
import { Bot } from "lucide-react"
import { useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { useParams } from "react-router-dom"
import { MessageContent } from "./DailyMessageContent"
import { GeneratedFileCards, pickGeneratedFiles, type GeneratedFile } from "./DailyGeneratedFiles"
import { locationContext } from "@/contexts/locationContext"
import { isMemoryToolEvent } from "@/components/bs-comp/appChat/memoryPlaceholder"

interface Message {
    messageId: string;
    sender: string;
    text: string;
    isCreatedByUser: boolean;
    user_name: string;
    source: number;
    generatedFiles: GeneratedFile[];
}

// v2.5: backend stores daily-mode `message.message` as JSON
// (`{query}` for questions, `{msg, events}` / older `{content, reasoning_content}`
// for agent answers). The admin `/chat/messages/:id` endpoint returns the raw
// column untransformed, so we normalize here to the same display string the
// client builds in parseStreamHistoryItem — plain text plus an optional
// `:::thinking\n...\n:::\n...` prefix that DailyMessageContent already renders.
function extractDisplayText(msg: any, memoryPlaceholder: string): string {
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

    // F132 (AC-09): never fall back to the raw JSON when it carries a memory tool event
    const hasMemoryEvent = Array.isArray(parsed.events)
        && parsed.events.some((e: unknown) => (e as { type?: unknown } | null)?.type === "tool_call" && isMemoryToolEvent(e));
    const body = content || (hasMemoryEvent ? memoryPlaceholder : "");

    if (reasoning) return `:::thinking\n${reasoning}\n:::\n${body}`;
    return body || raw;
}

export default function DailyChatDetail() {
    const { cid } = useParams()
    const [messages, setMessages] = useState<Message[]>([])
    const [loading, setLoading] = useState(true)
    const { appConfig } = useContext(locationContext)

    const { t } = useTranslation()
    // Read t through a ref so the history request does not re-run when t changes identity
    const tRef = useRef(t)
    tRef.current = t
    const title = messages.length > 0 ? messages[0].flow_name : ''

    useEffect(() => {
        getChatHistoryApi(cid).then((res: any) => {
            const items = Array.isArray(res) ? res : []
            const memoryPlaceholder = String(tRef.current('memory.operation'))
            const normalised = items.map((m: any) => ({
                ...m,
                text: extractDisplayText(m, memoryPlaceholder),
                generatedFiles: m.isCreatedByUser ? [] : pickGeneratedFiles(m.files),
            }))
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
        <div className="relative h-full">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <LoadingIcon />
            </div>}

            <div className="flex h-full flex-col bg-background-login px-4">
                <div className="flex shrink-0 justify-between items-center py-4">
                    <div className="flex items-center">
                        <Tooltip content={t('back')} side="top">
                            <Button size="medium" aria-label={t('back')} variant="outlined" onClick={() => window.history.back()} color="default" iconOnly><Outlined.ArrowLeft size={16} /></Button>
                        </Tooltip>
                        <span className=" text-gray-700 text-sm font-black pl-4">{t('log.detailedSession')}</span>
                    </div>
                </div>

                {/* messages */}
                <div className="min-h-0 flex-1 overflow-y-auto">
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
                                                <MessageContent text={msg.text} chatId={cid} files={msg.generatedFiles} />
                                                <GeneratedFileCards chatId={cid} files={msg.generatedFiles} />

                                                {msg.source === 1 && <div className="mt-2">
                                                    <Button variant="text" size="small" onClick={() => showResouce(msg.messageId, msg.text)} color="default">{t('chat.source')}</Button>
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

