import React, { forwardRef } from "react";
import { ReactComponent as Moon } from "./Moon.svg";

export const MoonIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Moon ref={ref} {...props} className={className || ''}/>;
});