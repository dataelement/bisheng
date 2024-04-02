import React, { forwardRef } from "react";
import { ReactComponent as System } from "./System.svg";

export const SystemIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <System ref={ref} {...props} className={className || ''}/>;
});