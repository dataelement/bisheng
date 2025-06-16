import React, { forwardRef } from "react";
import copy from "./copy.svg?react";
import like from "./like.svg?react";
import unLike from "./unLike.svg?react";
import sound from "./sound.svg?react";
import loading from "./loading.svg?react";
import { cname } from "@/components/bs-ui/utils";
type ThunmbIconType = 'copy' | 'like' | 'unLike' | 'copyDark' | 'likeDark' | 'unLikeDark' | 'sound' | 'loading';

export const ThunmbIcon = forwardRef<
    SVGSVGElement & { type: ThunmbIconType, className: string },
    React.PropsWithChildren<{ type: ThunmbIconType, className: string }>
>((props, ref) => {
    const comps = {
        'copy': copy,
        'like': like,
        'unLike': unLike,
        'sound': sound,
        'loading': loading
    }
    const Comp = comps[props.type];
    const _className = cname('transition text-gray-400 hover:text-gray-500', props.className)
    return <Comp ref={ref} {...props} className={_className} />;
});
