import React, { forwardRef } from "react";
import Github from "./Github.svg?react";

export const GithubIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Github ref={ref} {...props} className={className || ''} />;
});