import React, { forwardRef } from "react";
import Drag from "./Drag.svg?react";

export const RbDragIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Drag ref={ref} {...props} className={className || ''} />;
});