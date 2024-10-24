import React, { forwardRef } from "react";
import { ReactComponent as Label } from "./Label.svg";

export const LabelIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Label ref={ref} {...props} className={className || ''} />;
});