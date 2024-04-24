import React, { forwardRef } from "react";
import { ReactComponent as NewApplication } from "./NewApplication.svg";

export const NewApplicationIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({className,...props}, ref) => {
    return <NewApplication ref={ref} {...props} className={className || ''}/>;
});