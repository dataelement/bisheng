import React, { forwardRef } from "react";
import Technology from "./Technology.svg?react";

export const TechnologyIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Technology ref={ref} {...props} className={className || ''} />;
});