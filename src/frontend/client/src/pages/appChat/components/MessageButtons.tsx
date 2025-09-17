import { useState } from "react";
import { copyTrackingApi, likeChatApi } from "~/api/apps";
import MessageIcon from "~/components/ui/icon/Message";

const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

export default function MessageButtons({ id, onCopy, data, onUnlike, children = null }) {
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
        <MessageIcon
            type='copy'
            className={`cursor-pointer ${copied && 'text-primary hover:text-primary'}`}
            onClick={handleCopy}
        />
        <MessageIcon
            type='like'
            className={`cursor-pointer ${state === ThumbsState.ThumbsUp && 'text-primary hover:text-primary'}`}
            onClick={() => handleClick(ThumbsState.ThumbsUp)}
        />
        <MessageIcon
            type='unLike'
            className={`cursor-pointer ${state === ThumbsState.ThumbsDown && 'text-primary hover:text-primary'}`}
            onClick={() => handleClick(ThumbsState.ThumbsDown)}
        />
    </div>
};
