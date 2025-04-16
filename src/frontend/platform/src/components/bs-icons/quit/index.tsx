import React, { forwardRef } from "react";
import Quit from "./Quit.svg?react";

export const QuitIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Quit ref={ref} {...props} className={className || ''} />;
});