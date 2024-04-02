import React, { forwardRef } from "react";
import { ReactComponent as En } from "./En.svg";

export const EnIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <En ref={ref} {...props} className={className || ''}/>;
});