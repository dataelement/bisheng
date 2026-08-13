import { useState } from "react";
import { Outlined } from "bisheng-icons";
import { useRecoilValue, useSetRecoilState } from "recoil";
import { copyTrackingApi, disLikeCommentApi, likeChatApi } from "~/api/apps";
import { MessageFeedbackButtons } from "~/components/Chat/MessageFeedbackButtons";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";
import { chatIdState, chatsState } from "../store/atoms";

// Shared action-icon button — matches ExportSelectionButton (size-6 hit area,
// 14px bisheng-icons Outlined glyph, text-3 idle / brand-500 active) so the
// whole workflow action row reads as one consistent set.
const ACTION_BTN =
    "flex size-6 items-center justify-center rounded-md transition-colors hover:bg-fill-1";

export default function MessageButtons({ id, text, onCopy, data, children = null }) {
    const [copied, setCopied] = useState(false)
    const chatId = useRecoilValue(chatIdState)
    const setChats = useSetRecoilState(chatsState)

    // Messages live in the chatsState cache and are NOT refetched when the user
    // switches back to this conversation, so the new verdict must be written back
    // to the cached message or the highlight is lost on conversation switch.
    const handleLike = (liked: number) => {
        // returned so the confirmation toast waits for the request
        const pending = likeChatApi(id, liked)
        if (!chatId) return pending
        setChats((prev) => {
            const chat = prev[chatId]
            if (!chat?.messages) return prev
            return {
                ...prev,
                [chatId]: {
                    ...chat,
                    messages: chat.messages.map((msg) =>
                        msg.id === id ? { ...msg, liked } : msg
                    ),
                },
            }
        })
        return pending
    }

    const handleCopy = (e) => {
        setCopied(true)
        onCopy()
        setTimeout(() => {
            setCopied(false)
        }, 2000);

        copyTrackingApi(id) // 上报
    }

    return <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {children}
        <TextToSpeechButton messageId={String(id)} text={text} />
        <button
            type="button"
            className={ACTION_BTN}
            onClick={handleCopy}
            title={copied ? '已复制' : '复制'}
            aria-label="复制"
        >
            {copied
                ? <Outlined.Copied size={14} className="text-blue-500" />
                : <Outlined.Copy size={14} className="text-text-3" />}
        </button>
        <MessageFeedbackButtons
            liked={data}
            onLike={handleLike}
            onDislikeComment={(comment) => disLikeCommentApi(id, comment)}
        />
    </div>
};
