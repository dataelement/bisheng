import React, { forwardRef } from "react";
import Save from "./icon.svg?react";

export const SaveIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-0 ' + (className || '')
    return <Save ref={ref} {...props} className={_className} />;
});
