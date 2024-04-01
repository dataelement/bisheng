import React, { forwardRef } from "react";
import { ReactComponent as Knowledge } from "./Knowledge.svg";

export const KnowledgeIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Knowledge ref={ref} {...props} className={className || ''}/>;
});