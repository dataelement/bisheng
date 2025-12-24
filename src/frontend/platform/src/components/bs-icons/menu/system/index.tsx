import React, { forwardRef } from "react";
import System from "./System.svg?react";

export const SystemIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <System ref={ref} {...props} className={className || ''} />;
});


export const DashboardIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <svg ref={ref} {...props} className={className || ''}  fill="currentColor" width="24" height="24" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg">
        <path d="M469.333333 170.666667v170.666666a42.666667 42.666667 0 0 1-42.666666 42.666667H170.666667a42.666667 42.666667 0 0 1-42.666667-42.666667V170.666667a42.666667 42.666667 0 0 1 42.666667-42.666667h256a42.666667 42.666667 0 0 1 42.666666 42.666667z m-42.666666 298.666666H170.666667a42.666667 42.666667 0 0 0-42.666667 42.666667v341.333333a42.666667 42.666667 0 0 0 42.666667 42.666667h256a42.666667 42.666667 0 0 0 42.666666-42.666667v-341.333333a42.666667 42.666667 0 0 0-42.666666-42.666667z m426.666666 170.666667h-256a42.666667 42.666667 0 0 0-42.666666 42.666667v170.666666a42.666667 42.666667 0 0 0 42.666666 42.666667h256a42.666667 42.666667 0 0 0 42.666667-42.666667v-170.666666a42.666667 42.666667 0 0 0-42.666667-42.666667z m0-512h-256a42.666667 42.666667 0 0 0-42.666666 42.666667v341.333333a42.666667 42.666667 0 0 0 42.666666 42.666667h256a42.666667 42.666667 0 0 0 42.666667-42.666667V170.666667a42.666667 42.666667 0 0 0-42.666667-42.666667z"></path>
    </svg>;
});