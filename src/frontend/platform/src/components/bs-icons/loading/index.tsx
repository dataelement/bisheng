import React, { forwardRef } from "react";
import Load from "./Load.svg?react";
import { cname } from "../../bs-ui/utils";
import { withBrandBaseUrl } from "@/utils/brand";
import { BrandTickSpinner, isBuiltinLoadingIcon } from "./BrandTickSpinner";

export const LoadIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <Load ref={ref} {...props} className={cname('text-gray-50 animate-spin', className)} />;
});


export const LoadingIcon = forwardRef<
    (SVGSVGElement | HTMLImageElement) & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const rawIcon = window.BRAND_CONFIG?.URLLoadingIcon || window.BRAND_CONFIG?.loadingIcon || "";
    // Custom uploaded icon → <img> (cannot follow currentColor; intentional).
    if (rawIcon && !isBuiltinLoadingIcon(rawIcon)) {
        return <img src={withBrandBaseUrl(rawIcon)} ref={ref as React.ForwardedRef<HTMLImageElement>} {...props} className={cname('text-primary max-w-14', className, window.BRAND_CONFIG?.loadingAnimation)} />;
    }
    // Built-in default → inline spinner that follows --primary (admin theme).
    return <BrandTickSpinner ref={ref as React.ForwardedRef<SVGSVGElement>} {...props} className={cname('text-primary', className)} />;
});
