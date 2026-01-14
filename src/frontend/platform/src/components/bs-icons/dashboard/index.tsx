import { forwardRef } from "react";

export const FilterIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <svg ref={ref} {...props} className={className || ''} width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <g clip-path="url(#clip0_572_6083)">
            <path d="M3.66674 3.33325H12.3334C12.4294 3.36692 12.5164 3.42213 12.5878 3.49463C12.6592 3.56713 12.7131 3.65501 12.7452 3.75153C12.7774 3.84806 12.7871 3.95066 12.7735 4.0515C12.7598 4.15233 12.7233 4.24871 12.6667 4.33325L9.3334 7.99992V12.6666L6.66674 10.6666V7.99992L3.3334 4.33325C3.2768 4.24871 3.2403 4.15233 3.22669 4.0515C3.21309 3.95066 3.22274 3.84806 3.25491 3.75153C3.28709 3.65501 3.34093 3.56713 3.41231 3.49463C3.4837 3.42213 3.57073 3.36692 3.66674 3.33325Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
        </g>
        <defs>
            <clipPath id="clip0_572_6083">
                <rect width="16" height="16" fill="white" />
            </clipPath>
        </defs>
    </svg>
});


export const GridAddIcon = forwardRef<
    SVGSVGElement & { className: any },
    React.PropsWithChildren<{ className?: string }>
>(({ className, ...props }, ref) => {
    return <svg ref={ref} {...props} className={className || ''} width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <g clip-path="url(#clip0_572_6079)">
            <path d="M5.99984 2.66675H3.33317C2.96498 2.66675 2.6665 2.96522 2.6665 3.33341V6.00008C2.6665 6.36827 2.96498 6.66675 3.33317 6.66675H5.99984C6.36803 6.66675 6.6665 6.36827 6.6665 6.00008V3.33341C6.6665 2.96522 6.36803 2.66675 5.99984 2.66675Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M12.6668 2.66675H10.0002C9.63197 2.66675 9.3335 2.96522 9.3335 3.33341V6.00008C9.3335 6.36827 9.63197 6.66675 10.0002 6.66675H12.6668C13.035 6.66675 13.3335 6.36827 13.3335 6.00008V3.33341C13.3335 2.96522 13.035 2.66675 12.6668 2.66675Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M5.99984 9.33325H3.33317C2.96498 9.33325 2.6665 9.63173 2.6665 9.99992V12.6666C2.6665 13.0348 2.96498 13.3333 3.33317 13.3333H5.99984C6.36803 13.3333 6.6665 13.0348 6.6665 12.6666V9.99992C6.6665 9.63173 6.36803 9.33325 5.99984 9.33325Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M11.3335 9.33325V13.3333M9.3335 11.3333H13.3335H9.3335Z" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" />
        </g>
        <defs>
            <clipPath id="clip0_572_6079">
                <rect width="16" height="16" fill="white" />
            </clipPath>
        </defs>
    </svg>
});


