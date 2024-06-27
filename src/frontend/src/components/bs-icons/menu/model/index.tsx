import React, { forwardRef } from "react";
import { ReactComponent as Model } from "./Model.svg";

export const ModelIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <Model ref={ref} {...props} className={className || ''}/>;
});