import React, { forwardRef } from "react";
import { cn } from "~/utils";

const ABSOLUTE_URL_PATTERN = /^(https?:|data:|blob:|\/\/)/i;

function withBrandBaseUrl(url = "") {
    if (!url) return "";
    if (ABSOLUTE_URL_PATTERN.test(url)) return url;

    const baseUrl = (__APP_ENV__.BASE_URL || "").replace(/\/$/, "");
    if (baseUrl && (url === baseUrl || url.startsWith(`${baseUrl}/`))) return url;

    const normalizedUrl = url.startsWith("/") ? url : `/${url}`;
    return `${baseUrl}${normalizedUrl}`;
}

function getBrandLoadingIconUrl() {
    return withBrandBaseUrl(
        window.BRAND_CONFIG?.URLLoadingIcon
        || window.BRAND_CONFIG?.loadingIcon
        || window.BRAND_CONFIG?.loading?.icon?.url
        || "",
    );
}

export const LoadingIcon = forwardRef<
    (SVGSVGElement | HTMLImageElement) & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const loadingIcon = getBrandLoadingIconUrl();
    if (loadingIcon) {
        return (
            <img
                ref={ref as React.ForwardedRef<HTMLImageElement>}
                src={loadingIcon}
                alt=""
                {...props}
                className={cn('text-primary', className || 'max-w-14', window.BRAND_CONFIG?.loadingAnimation)}
            />
        );
    }

    return <svg ref={ref as React.ForwardedRef<SVGSVGElement>} {...props} className={cn('text-primary', className)} viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" width="80" height="80">
        <rect x="10" y="8" width="3" height="2" rx="1" fill="currentColor"></rect>
        <rect x="14" y="8" width="10" height="2" rx="1" fill="currentColor">
            <animate attributeName="width" values="12;7;12" dur="1s" repeatCount="indefinite" begin="-0.3s" />
        </rect>
        <rect x="11" y="11.5" width="16" height="2" rx="1" fill="currentColor">
            <animate attributeName="width" values="18;14;18" dur="1s" repeatCount="indefinite" begin="-0.6s" />
        </rect>
        <rect x="11" y="15" width="12" height="2" rx="1" fill="currentColor">
            <animate attributeName="width" values="14;10;14" dur="1s" repeatCount="indefinite" begin="-0.9s" />
        </rect>
        <rect x="11" y="18.5" width="14" height="2" rx="1" fill="currentColor">
            <animate attributeName="width" values="16;12;16" dur="1s" repeatCount="indefinite" begin="-0.2s" />
        </rect>
        <rect x="11" y="22" width="16" height="2" rx="1" fill="currentColor">
            <animate attributeName="width" values="18;14;18" dur="1s" repeatCount="indefinite" begin="-1.5s" />
        </rect>
        <rect x="10" y="25.5" width="10" height="2" rx="1" fill="currentColor">
            <animate attributeName="width" values="12;9;12" dur="1s" repeatCount="indefinite" begin="-0.1s" />
        </rect>
        <rect x="21" y="25.5" width="3" height="2" rx="1" fill="currentColor">
            <animate attributeName="x" values="23;20;23" dur="1s" repeatCount="indefinite" begin="-0.1s" />
        </rect>
    </svg>
});
