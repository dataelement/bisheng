import React, { forwardRef } from "react";
import { ReactComponent as Knowledge } from "./Evaluation.svg";

export const EvaluatingIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Knowledge ref={ref} {...props} className={className || ''}/>;
});