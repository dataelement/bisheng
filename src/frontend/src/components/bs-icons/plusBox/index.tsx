import React, { forwardRef } from "react";
import { ReactComponent as PlusBox } from "./PlusBox.svg";

export const PlusBoxIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <PlusBox ref={ref} {...props} className={_className} />;
});
