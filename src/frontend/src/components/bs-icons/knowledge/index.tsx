import React, { forwardRef } from "react";
import Knowledge from "./Knowledge.svg?react";

export const KnowledgeIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Knowledge ref={ref} {...props} className={className || ''} />;
});