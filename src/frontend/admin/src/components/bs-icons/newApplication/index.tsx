import React, { forwardRef } from "react";
import NewApplication from "./NewApplication.svg?react";

export const NewApplicationIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <NewApplication ref={ref} {...props} className={className || ''} />;
});