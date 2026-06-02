import { useState } from "react";
import { Outlined } from "bisheng-icons";
import { copyTrackingApi, likeChatApi } from "~/api/apps";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";
import { cn } from "~/utils";

const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

// Shared action-icon button — matches ExportSelectionButton (size-6 hit area,
// 14px bisheng-icons Outlined glyph, #818181 idle / #1677ff active) so the
// whole workflow action row reads as one consistent set.
const ACTION_BTN =
    "flex size-6 items-center justify-center rounded-[6px] transition-colors hover:bg-[#F7F7F7]";

export default function MessageButtons({ id, text, onCopy, data, onUnlike, children = null }) {
    const [state, setState] = useState<ThumbsState>(data)
    const [copied, setCopied] = useState(false)

    const handleClick = (type: ThumbsState) => {
        setState(_type => {
            const newType = type === _type ? ThumbsState.Default : type
            // api
            likeChatApi(id, newType);
            return newType
        })
        if (state !== ThumbsState.ThumbsDown && type === ThumbsState.ThumbsDown) onUnlike?.(id)
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
                ? <Outlined.Copied size={14} className="text-[#1677ff]" />
                : <Outlined.Copy size={14} className="text-[#818181]" />}
        </button>
        <button
            type="button"
            className={ACTION_BTN}
            onClick={() => handleClick(ThumbsState.ThumbsUp)}
            title="点赞"
            aria-label="点赞"
            aria-pressed={state === ThumbsState.ThumbsUp}
        >
            <Outlined.ThumbsUp
                size={14}
                className={cn(state === ThumbsState.ThumbsUp ? 'text-[#1677ff]' : 'text-[#818181]')}
            />
        </button>
        <button
            type="button"
            className={ACTION_BTN}
            onClick={() => handleClick(ThumbsState.ThumbsDown)}
            title="点踩"
            aria-label="点踩"
            aria-pressed={state === ThumbsState.ThumbsDown}
        >
            <Outlined.ThumbsDown
                size={14}
                className={cn(state === ThumbsState.ThumbsDown ? 'text-[#1677ff]' : 'text-[#818181]')}
            />
        </button>
    </div>
};
