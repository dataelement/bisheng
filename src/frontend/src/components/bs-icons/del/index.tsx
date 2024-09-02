import React, { forwardRef } from "react";
import { ReactComponent as Del } from "./Del.svg";
import { ReactComponent as Trash } from "./Trash.svg";

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