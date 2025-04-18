import React, { forwardRef } from "react";
import Upload from "./icon.svg?react";

export const UploadIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const _className = 'transition text-gray-950 ' + (className || '')
    return <Upload ref={ref} {...props} className={_className} />;
});
