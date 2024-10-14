import React, { forwardRef } from "react";
import System from "./System.svg?react";

export const SystemIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <System ref={ref} {...props} className={className || ''} />;
});