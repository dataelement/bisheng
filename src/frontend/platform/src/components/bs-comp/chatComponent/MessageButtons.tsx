// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import { FlagIcon } from "@/components/bs-icons";

import { AudioPlayComponent } from "@/components/voiceFunction/audioPlayButton";
import { copyTrackingApi,likeChatApi } from "@/controllers/API";
import { useLinsightConfig } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";

const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

export default function MessageButtons({ debug, mark = false, id, onCopy, data, onUnlike, onMarkClick, version, text = '' }) {

    const { t } = useTranslation()
    const [state, setState] = useState<ThumbsState>(data)
    const [copied, setCopied] = useState(false)

    const { data: linsightConfig, isLoading: loading, refetch: refetchConfig, error } = useLinsightConfig();
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

    return <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {mark && <Button className="h-6 text-xs group-hover:opacity-100 opacity-0" onClick={onMarkClick}>
            <FlagIcon width={12} height={12} className="cursor-pointer" />
            <span>{t('addQa')}</span>
        </Button>}
        {!mark && linsightConfig?.tts_model?.id && (
            <AudioPlayComponent
                messageId={String(id)}
                msg={text}
            />
        )}

        {!debug && (version === 'v2') &&
            <>
                <Outlined.Copy
                    className={`size-4 cursor-pointer ${copied ? 'text-primary' : 'text-text-3 hover:text-text-2'}`}
                    onClick={handleCopy}
                />
                <Outlined.ThumbsUp
                    className={`size-4 cursor-pointer ${state === ThumbsState.ThumbsUp ? 'text-primary' : 'text-text-3 hover:text-text-2'}`}
                    onClick={() => handleClick(ThumbsState.ThumbsUp)}
                />
                <Outlined.ThumbsDown
                    className={`size-4 cursor-pointer ${state === ThumbsState.ThumbsDown ? 'text-primary' : 'text-text-3 hover:text-text-2'}`}
                    onClick={() => handleClick(ThumbsState.ThumbsDown)}
                /></>
        }

    </div>
};
