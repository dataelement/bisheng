import { useState } from "react";
import { Outlined } from "bisheng-icons";
import { copyTrackingApi, disLikeCommentApi, likeChatApi } from "~/api/apps";
import { MessageFeedbackButtons } from "~/components/Chat/MessageFeedbackButtons";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";

// Shared action-icon button — matches ExportSelectionButton (size-6 hit area,
// 14px bisheng-icons Outlined glyph, #818181 idle / brand-500 active) so the
// whole workflow action row reads as one consistent set.
const ACTION_BTN =
    "flex size-6 items-center justify-center rounded-[6px] transition-colors hover:bg-[#F7F7F7]";

export default function MessageButtons({ id, text, onCopy, data, children = null }) {
    const [copied, setCopied] = useState(false)

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
                : <Outlined.Copy size={14} className="text-[#818181]" />}
        </button>
        <MessageFeedbackButtons
            liked={data}
            onLike={(liked) => likeChatApi(id, liked)}
            onDislikeComment={(comment) => disLikeCommentApi(id, comment)}
        />
    </div>
};
