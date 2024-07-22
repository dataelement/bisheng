import React, { forwardRef } from "react";
import { ReactComponent as Label } from "./Label.svg";

export const LabelIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Label ref={ref} {...props} className={_className} />;
});