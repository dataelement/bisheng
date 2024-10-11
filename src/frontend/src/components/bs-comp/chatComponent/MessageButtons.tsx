import { FlagIcon } from "@/components/bs-icons";
import { ThunmbIcon } from "@/components/bs-icons/thumbs";
import { Button } from "@/components/bs-ui/button";
import { copyTrackingApi, likeChatApi } from "@/controllers/API";
import { useState } from "react";
import { useTranslation } from "react-i18next";

const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

export default function MessageButtons({ mark = false, id, onCopy, data, onUnlike, onMarkClick }) {
    const { t } = useTranslation()
    const [state, setState] = useState<ThumbsState>(data)
    const [copied, setCopied] = useState(false)

    const handleClick = (type: ThumbsState) => {
        if (mark) return
        setState(_type => {
            const newType = type === _type ? ThumbsState.Default : type
            // api
            likeChatApi(id, newType);
            return newType
        })
        if (state !== ThumbsState.ThumbsDown && type === ThumbsState.ThumbsDown) onUnlike?.(id)
    }

    const handleCopy = (e) => {
        if (mark) return
        setCopied(true)
        onCopy()
        setTimeout(() => {
            setCopied(false)
        }, 2000);

        copyTrackingApi(id)
    }

    return <div className="flex gap-1">
        {mark && <Button className="h-6 text-xs group-hover:opacity-100 opacity-0" onClick={onMarkClick}>
            <FlagIcon width={12} height={12} className="cursor-pointer" />
            <span>{t('addQa')}</span>
        </Button>}
        <ThunmbIcon
            type='copy'
            className={`cursor-pointer ${copied && 'text-primary hover:text-primary'}`}
            onClick={handleCopy}
        />
        <ThunmbIcon
            type='like'
            className={`cursor-pointer ${state === ThumbsState.ThumbsUp && 'text-primary hover:text-primary'}`}
            onClick={() => handleClick(ThumbsState.ThumbsUp)}
        />
        <ThunmbIcon
            type='unLike'
            className={`cursor-pointer ${state === ThumbsState.ThumbsDown && 'text-primary hover:text-primary'}`}
            onClick={() => handleClick(ThumbsState.ThumbsDown)}
        />
    </div>
};
