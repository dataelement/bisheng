import React, { forwardRef } from "react";
import Load from "./Load.svg?react";
import Loading from "./Loading.svg?react";
import { cname } from "../../bs-ui/utils";

export const LoadIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Load ref={ref} {...props} className={cname('text-gray-50 animate-spin', className)} />;
});


export const LoadingIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Loading ref={ref} {...props} className={cname('text-primary', className)} />;
});