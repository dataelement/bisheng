import React, { forwardRef } from "react";
import { ReactComponent as PlusBox } from "./PlusBox.svg";
import { ReactComponent as PlusBoxDark } from "./PlusBox-dark.svg";

export const PlusBoxIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <PlusBox ref={ref} {...props} className={_className} />;
});

export const PlusBoxIconDark = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <PlusBoxDark ref={ref} {...props} className={_className} />;
});
