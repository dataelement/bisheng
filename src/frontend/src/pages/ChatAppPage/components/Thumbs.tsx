import { ThumbsDown, ThumbsUp, Clipboard, ClipboardCheck } from "lucide-react";
import { useState } from "react";
import { likeChatApi } from "../../../controllers/API";
import { classNames } from "../../../utils";

const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

export default function Thumbs({ id, className, onCopy, data, onDislike }) {

    const [state, setState] = useState<ThumbsState>(data)
    const [copied, setCopied] = useState(false)

    const handleClick = (type: ThumbsState) => {
        setState(_type => {
            const newType = type === _type ? ThumbsState.Default : type
            // api
            likeChatApi(id, newType);
            return newType
        })
        if (state !== ThumbsState.ThumbsDown && type === ThumbsState.ThumbsDown) onDislike?.(id)
    }

    const handleCopy = (e) => {
        setCopied(true)
        onCopy(e.target.parentNode.parentNode)
        setTimeout(() => {
            setCopied(false)
        }, 2000);
    }

    return <div className={classNames('flex gap-2', className)}>
        {copied ? <ClipboardCheck size={18} className="text-blue-400"></ClipboardCheck> :
            <Clipboard
                size={18}
                className={`cursor-pointer hover:text-blue-400 text-gray-300`}
                onClick={handleCopy} />
        }
        <ThumbsUp
            size={18}
            className={`cursor-pointer hover:text-blue-400 ${state === ThumbsState.ThumbsUp ? 'text-blue-400' : 'text-gray-300'}`}
            onClick={() => handleClick(ThumbsState.ThumbsUp)} />
        <ThumbsDown
            size={18}
            className={`cursor-pointer hover:text-blue-400 ${state === ThumbsState.ThumbsDown ? 'text-blue-400' : 'text-gray-300'}`}
            onClick={() => handleClick(ThumbsState.ThumbsDown)} />
    </div>
}
