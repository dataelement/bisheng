import React, { forwardRef } from "react";
import { ReactComponent as Upload } from "./icon.svg";

export const UploadIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Upload ref={ref} {...props} className={_className} />;
});
