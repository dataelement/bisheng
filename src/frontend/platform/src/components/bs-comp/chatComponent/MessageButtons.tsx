import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FlagIcon } from "@/components/bs-icons";
import { ThunmbIcon } from "@/components/bs-icons/thumbs";
import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { copyTrackingApi, disLikeCommentApi, likeChatApi } from "@/controllers/API";
import { AudioPlayComponent } from "@/components/AudioPlayComponent";


const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

export default function MessageButtons({ mark = false, id, onCopy, data, onUnlike, onMarkClick, msgVNode, onlyRead = false, chatId, msg = '' }) {
    const { t } = useTranslation()
    const [state, setState] = useState<ThumbsState>(data)
    const [copied, setCopied] = useState(false)
    const { message } = useToast()

    const handleClick = (type: ThumbsState) => {
        if (mark || onlyRead) return
        setState(_type => {
            const isRecover = type === _type;
            const newType = isRecover ? ThumbsState.Default : type
            // api
            likeChatApi(id, newType);
            // 状态不是点踩 则应该把评论置为空
            (newType !== ThumbsState.ThumbsDown) && disLikeCommentApi(id, '');
            return newType
        })
        if (state !== ThumbsState.ThumbsDown && type === ThumbsState.ThumbsDown) onUnlike?.(id)
    }

    const handleCopy = (e) => {
        if (mark || onlyRead) return
        setCopied(true)
        onCopy()
        setTimeout(() => {
            setCopied(false)
        }, 2000);

        copyTrackingApi(id)
        message({
            variant: 'success',
            description: '已复制'
        })
    }

    return <div>
        <div className="flex justify-end gap-1">
        {mark && <Button className="h-6 text-xs group-hover:opacity-100 opacity-0" onClick={onMarkClick}>
            <FlagIcon width={12} height={12} className={`${!onlyRead && 'cursor-pointer'}`} />
            <span>{t('addQa')}</span>
        </Button>}
        <AudioPlayComponent
            messageId={chatId}
            msg={msg}
        />
        <ThunmbIcon
            type='copy'
            className={`${!onlyRead && 'cursor-pointer'} ${copied && 'text-primary hover:text-primary'}`}
            onClick={handleCopy}
        />
        <ThunmbIcon
            type='like'
            className={`${!onlyRead && 'cursor-pointer'} ${state === ThumbsState.ThumbsUp && 'text-primary hover:text-primary'}`}
            onClick={() => handleClick(ThumbsState.ThumbsUp)}
        />
        <ThunmbIcon
            type='unLike'
            className={`${!onlyRead && 'cursor-pointer'} ${state === ThumbsState.ThumbsDown && 'text-primary hover:text-primary'}`}
            onClick={() => handleClick(ThumbsState.ThumbsDown)}
        />
        </div>
        { msgVNode }
    </div>
};
