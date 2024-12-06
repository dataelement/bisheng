import React, { forwardRef } from "react";
import Application from "./Application.svg?react";

export const ApplicationIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Application ref={ref} {...props} className={className || ''} />;
});