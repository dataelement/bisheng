import React, { forwardRef } from "react";
import { cn } from "~/utils";
import "./brandSpinner.css";

const ABSOLUTE_URL_PATTERN = /^(https?:|data:|blob:|\/\/)/i;

// The 12-tick spinner shape (Figma export, viewBox 0 0 400 400). Filled with
// currentColor and faded via the conic mask in brandSpinner.css.
const TICK_SPINNER_PATH =
    "M202.5 263.685C208.095 263.685 212.632 268.22 212.632 273.815V299.868C212.632 305.464 208.096 310 202.5 310C196.904 310 192.368 305.464 192.368 299.868V273.815C192.368 268.22 196.905 263.685 202.5 263.685ZM156.818 258.86C159.616 254.015 165.812 252.355 170.658 255.152C175.504 257.95 177.164 264.146 174.366 268.992L161.34 291.555C158.542 296.4 152.346 298.06 147.5 295.263C142.654 292.465 140.994 286.269 143.792 281.423L156.818 258.86ZM234.342 255.152C239.188 252.355 245.384 254.015 248.182 258.86L261.208 281.423C264.006 286.269 262.346 292.465 257.5 295.263C252.654 298.06 246.458 296.4 243.66 291.555L230.634 268.992C227.836 264.146 229.496 257.95 234.342 255.152ZM257.652 231.842C260.45 226.996 266.646 225.336 271.492 228.134L294.055 241.16C298.9 243.958 300.56 250.154 297.763 255C294.965 259.846 288.769 261.506 283.923 258.708L261.36 245.682C256.515 242.884 254.855 236.688 257.652 231.842ZM133.508 228.134C138.354 225.336 144.55 226.996 147.348 231.842C150.145 236.688 148.485 242.884 143.64 245.682L121.077 258.708C116.231 261.506 110.035 259.846 107.237 255C104.44 250.154 106.1 243.958 110.945 241.16L133.508 228.134ZM128.685 189.868C134.28 189.868 138.815 194.405 138.815 200C138.815 205.595 134.28 210.132 128.685 210.132H102.632C97.0363 210.132 92.5 205.596 92.5 200C92.5 194.404 97.0363 189.868 102.632 189.868H128.685ZM302.368 189.868C307.964 189.868 312.5 194.404 312.5 200C312.5 205.596 307.964 210.132 302.368 210.132H276.315C270.72 210.132 266.185 205.595 266.185 200C266.185 194.405 270.72 189.868 276.315 189.868H302.368ZM107.237 145C110.035 140.154 116.231 138.494 121.077 141.292L143.64 154.318C148.485 157.116 150.145 163.312 147.348 168.158C144.55 173.004 138.354 174.664 133.508 171.866L110.945 158.84C106.1 156.042 104.44 149.846 107.237 145ZM283.923 141.292C288.769 138.494 294.965 140.154 297.763 145C300.56 149.846 298.9 156.042 294.055 158.84L271.492 171.866C266.646 174.664 260.45 173.004 257.652 168.158C254.855 163.313 256.515 157.116 261.36 154.318L283.923 141.292ZM147.5 104.737C152.346 101.94 158.542 103.6 161.34 108.445L174.366 131.008C177.164 135.854 175.504 142.05 170.658 144.848C165.812 147.645 159.616 145.985 156.818 141.14L143.792 118.577C140.994 113.731 142.654 107.535 147.5 104.737ZM243.66 108.445C246.458 103.6 252.654 101.94 257.5 104.737C262.346 107.535 264.006 113.731 261.208 118.577L248.182 141.14C245.384 145.985 239.188 147.645 234.342 144.848C229.496 142.05 227.836 135.854 230.634 131.008L243.66 108.445ZM202.5 90C208.096 90 212.632 94.5363 212.632 100.132V126.185C212.632 131.78 208.095 136.315 202.5 136.315C196.905 136.315 192.368 131.78 192.368 126.185V100.132C192.368 94.5363 196.904 90 202.5 90Z";

// Built-in default loading asset shipped in /public. When the brand config
// points at this (i.e. no custom uploaded icon), render the inline, theme-color
// spinner instead of an <img> — an <img> can't inherit currentColor, so it
// could never follow the workbench theme.
const BUILTIN_LOADING_ASSET = "/assets/bisheng/loading.svg";

function withBrandBaseUrl(url = "") {
    if (!url) return "";
    if (ABSOLUTE_URL_PATTERN.test(url)) return url;

    const baseUrl = (__APP_ENV__.BASE_URL || "").replace(/\/$/, "");
    if (baseUrl && (url === baseUrl || url.startsWith(`${baseUrl}/`))) return url;

    const normalizedUrl = url.startsWith("/") ? url : `/${url}`;
    return `${baseUrl}${normalizedUrl}`;
}

function getBrandLoadingIconUrl() {
    return (
        window.BRAND_CONFIG?.URLLoadingIcon
        || window.BRAND_CONFIG?.loadingIcon
        || window.BRAND_CONFIG?.loading?.icon?.url
        || ""
    );
}

/** True when the configured loading icon is the built-in default asset. */
function isBuiltinLoadingIcon(rawUrl: string) {
    return !rawUrl || rawUrl.replace(/[?#].*$/, "").endsWith(BUILTIN_LOADING_ASSET);
}

export const LoadingIcon = forwardRef<
    (SVGSVGElement | HTMLImageElement) & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    const rawLoadingIcon = getBrandLoadingIconUrl();

    // Custom uploaded icon → <img>. (Cannot be recolored; that is intentional.)
    if (!isBuiltinLoadingIcon(rawLoadingIcon)) {
        return (
            <img
                ref={ref as React.ForwardedRef<HTMLImageElement>}
                src={withBrandBaseUrl(rawLoadingIcon)}
                alt=""
                {...props}
                className={cn('text-primary', className || 'max-w-14', window.BRAND_CONFIG?.loadingAnimation)}
            />
        );
    }

    // Built-in default → inline tick spinner that follows --primary (workbench theme).
    return (
        <svg
            ref={ref as React.ForwardedRef<SVGSVGElement>}
            {...props}
            className={cn('bs-tick-spinner text-primary', className)}
            viewBox="0 0 400 400"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            width="80"
            height="80"
            aria-hidden="true"
        >
            <path fill="currentColor" d={TICK_SPINNER_PATH} />
        </svg>
    );
});
