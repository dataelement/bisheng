import React, { forwardRef } from "react";
import { ReactComponent as copy } from "./copy.svg";
import { ReactComponent as like } from "./like.svg";
import { ReactComponent as unLike } from "./unLike.svg";
import { cname } from "@/components/bs-ui/utils";

type ThunmbIconType = 'copy' | 'like' | 'unLike' | 'copyDark' | 'likeDark' | 'unLikeDark';

export const ThunmbIcon = forwardRef<
    SVGSVGElement & { type: ThunmbIconType, className: string },
    React.PropsWithChildren<{ type: ThunmbIconType, className: string }>
>((props, ref) => {
    const comps = {
        'copy': copy,
        'like': like,
        'unLike': unLike,
    }
    const Comp = comps[props.type];
    const _className = cname('transition text-gray-400 hover:text-gray-500', props.className)
    return <Comp ref={ref} {...props} className={_className} />;
});
