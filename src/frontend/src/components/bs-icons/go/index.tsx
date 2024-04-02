import React, { forwardRef } from "react";
import { ReactComponent as Go } from "./Go.svg";

export const GoIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Go ref={ref} {...props} className={_className} />;
});
