import React, { forwardRef } from "react";
import Plus from "./Plus.svg?react";

export const PlusIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Plus ref={ref} {...props} className={_className} />;
});
