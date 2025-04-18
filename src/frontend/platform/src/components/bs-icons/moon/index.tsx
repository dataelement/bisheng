import React, { forwardRef } from "react";
import Moon from "./Moon.svg?react";

export const MoonIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Moon ref={ref} {...props} className={className || ''} />;
});