import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { classNames } from "../../../utils";

const enum ThumbsState {
    Default = 0,
    ThumbsUp,
    ThumbsDown
}

export default function Thumbs({ id, className, data }) {

    const [state, setState] = useState<ThumbsState>(data)

    const handleClick = (type: ThumbsState) => {
        setState(_type => {
            const newType = type === _type ? ThumbsState.Default : type
            // api
            console.log('newType :>> ', newType);
            return newType
        })
    }

    return <div className={classNames('flex gap-2', className)}>
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
