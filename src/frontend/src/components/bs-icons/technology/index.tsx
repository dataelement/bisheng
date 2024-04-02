import React, { forwardRef } from "react";
import { ReactComponent as Technology } from "./Technology.svg";

export const TechnologyIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Technology ref={ref} {...props} className={className || ''}/>;
});