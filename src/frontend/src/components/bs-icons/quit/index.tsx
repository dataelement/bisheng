import React, { forwardRef } from "react";
import { ReactComponent as Quit } from "./Quit.svg";

export const QuitIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Quit ref={ref} {...props} className={className || ''} />;
});