import React, { forwardRef } from "react";
import { ReactComponent as AddTo } from "./AddTo.svg";

export const AddToIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-400 ' + (className || '')
    return <AddTo ref={ref} {...props} className={_className} />;
});
