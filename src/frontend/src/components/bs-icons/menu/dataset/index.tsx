import React, { forwardRef } from "react";
import { ReactComponent as Dataset } from "./Dataset.svg";

export const DatasetIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Dataset ref={ref} {...props} className={className || ''} />;
});