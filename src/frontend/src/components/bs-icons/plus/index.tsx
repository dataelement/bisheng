import React, { forwardRef } from "react";
import { ReactComponent as Plus } from "./Plus.svg";

export const PlusIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Plus ref={ref} {...props} className={_className} />;
});
