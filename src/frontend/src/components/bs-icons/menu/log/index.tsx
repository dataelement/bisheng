import React, { forwardRef } from "react";
import Log from "./Log.svg?react";

export const LogIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Log ref={ref} {...props} className={className || ''} />;
});