import React, { forwardRef } from "react";
import { ReactComponent as copy } from "./copy.svg";
import { ReactComponent as copyDark } from "./copyDark.svg";
import { ReactComponent as like } from "./like.svg";
import { ReactComponent as likeDark } from "./likeDark.svg";
import { ReactComponent as unLike } from "./unLike.svg";
import { ReactComponent as unLikeDark } from "./unLikeDark.svg";


type ThunmbIconType = 'copy' | 'like' | 'unLike' | 'copyDark' | 'likeDark' | 'unLikeDark';

export const ThunmbIcon = forwardRef<
    SVGSVGElement & { type: ThunmbIconType, className: string },
    React.PropsWithChildren<{ type: ThunmbIconType, className: string }>
>((props, ref) => {
    const comps = {
        'copy': copy,
        'copyDark': copyDark,
        'like': like,
        'likeDark': likeDark,
        'unLike': unLike,
        'unLikeDark': unLikeDark,
    }
    const Comp = comps[props.type];
    const _className = 'transition text-gray-400 ' + (props.className || '')
    return <Comp ref={ref} {...props} className={_className} />;
});
