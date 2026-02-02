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
    if (window.BRAND_CONFIG.loadingIcon) {
        return <img src={window.BRAND_CONFIG.loadingIcon} ref={ref} {...props} className={cname('text-primary max-w-14', className, window.BRAND_CONFIG.loadingAnimation)} />;
    }
    return <Loading ref={ref} {...props} className={cname('text-primary', className)} />;
});