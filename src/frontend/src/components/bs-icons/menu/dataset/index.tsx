import React, { forwardRef } from "react";
import Dataset from "./Dataset.svg?react";

export const DatasetIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Dataset ref={ref} {...props} className={className || ''} />;
});