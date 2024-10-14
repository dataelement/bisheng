import React, { forwardRef } from "react";
import Icon from "./Evaluation.svg?react";

export const EvaluatingIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Icon ref={ref} {...props} className={className || ''} />;
});