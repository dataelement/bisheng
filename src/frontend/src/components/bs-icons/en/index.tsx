import React, { forwardRef } from "react";
import En from "./En.svg?react";

export const EnIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <En ref={ref} {...props} className={className || ''} />;
});