import React, { forwardRef } from "react";
import { ReactComponent as Icon } from "./Evaluation.svg";

export const EvaluatingIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Icon ref={ref} {...props} className={className || ''} />;
});