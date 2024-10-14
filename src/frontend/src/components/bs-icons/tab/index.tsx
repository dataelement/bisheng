import React, { forwardRef } from "react";
import Tab from "./icon.svg?react";

export const TabIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Tab ref={ref} {...props} className={_className} />;
});
