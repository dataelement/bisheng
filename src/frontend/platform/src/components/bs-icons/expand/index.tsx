import React, { forwardRef } from "react";

export const ExpandIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <svg ref={ref} {...props} className={className || ''} width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M2 2.66675H14" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M2 8H6.66667" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M2 13.3333H14" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M12 6L14 8L12 10" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M14 8H10" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
});


