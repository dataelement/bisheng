import React, { forwardRef } from "react";
import Model from "./Model.svg?react";

export const ModelIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Model ref={ref} {...props} className={className || ''} />;
});