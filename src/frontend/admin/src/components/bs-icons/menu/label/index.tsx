import React, { forwardRef } from "react";
import Label from "./Label.svg?react";

export const LabelIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Label ref={ref} {...props} className={className || ''} />;
});