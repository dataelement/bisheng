import { useState } from "react";
import { copyTrackingApi, likeChatApi } from "~/api/apps";
import { SingleIconButton } from "bisheng-design-system/src/components/Button";
import Copy from "bisheng-design-system/src/icons/outlined/Copy";
import Copied from "bisheng-design-system/src/icons/outlined/Copied";
import ThumbsUp from "bisheng-design-system/src/icons/outlined/ThumbsUp";
import ThumbsDown from "bisheng-design-system/src/icons/outlined/ThumbsDown";
import { cn } from "~/utils";
import { TextToSpeechButton } from "~/components/Voice/TextToSpeechButton";
import MoreActionsDropdown from "~/components/Chat/MoreActionsDropdown";

const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

export default function MessageButtons({ id, text, onCopy, data, onUnlike }) {
    const [state, setState] = useState<ThumbsState>(data)
    const [copied, setCopied] = useState(false)

    const handleClick = (type: ThumbsState) => {
        setState(_type => {
            const newType = type === _type ? ThumbsState.Default : type
            likeChatApi(id, newType);
            return newType
        })
        if (state !== ThumbsState.ThumbsDown && type === ThumbsState.ThumbsDown) onUnlike?.(id)
    }

    const handleCopy = () => {
        setCopied(true)
        onCopy()
        setTimeout(() => {
            setCopied(false)
        }, 2000);

        copyTrackingApi(id)
    }

    return <div className="flex gap-1">
        <TextToSpeechButton messageId={String(id)} text={text} />
        <SingleIconButton
            variant="ghost"
            size="mini"
            icon={copied ? <Copied /> : <Copy />}
            aria-label="复制"
            className={cn("text-gray-400 hover:text-gray-500", copied && 'text-primary hover:text-primary')}
            onClick={handleCopy}
        />
        <SingleIconButton
            variant="ghost"
            size="mini"
            icon={<ThumbsUp />}
            aria-label="点赞"
            className={cn("text-gray-400 hover:text-gray-500", state === ThumbsState.ThumbsUp && 'text-primary hover:text-primary')}
            onClick={() => handleClick(ThumbsState.ThumbsUp)}
        />
        <SingleIconButton
            variant="ghost"
            size="mini"
            icon={<ThumbsDown />}
            aria-label="踩"
            className={cn("text-gray-400 hover:text-gray-500", state === ThumbsState.ThumbsDown && 'text-primary hover:text-primary')}
            onClick={() => handleClick(ThumbsState.ThumbsDown)}
        />
        <MoreActionsDropdown />
    </div>
};
