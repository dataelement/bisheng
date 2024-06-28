import React, { forwardRef } from "react";
import { ReactComponent as Log } from "./Log.svg";

export const LogIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Log ref={ref} {...props} className={className || ''} />;
});