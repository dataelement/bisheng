import React, { forwardRef } from "react";
import { ReactComponent as Application } from "./Application.svg";

export const ApplicationIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Application ref={ref} {...props} className={className || ''}/>;
});