import React, { forwardRef } from "react";
import Del from "./Del.svg?react";
import Trash from "./Trash.svg?react";

export const DelIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Del ref={ref} {...props} />;
});


export const TrashIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>((props, ref) => {
    return <Trash ref={ref} {...props} />;
});