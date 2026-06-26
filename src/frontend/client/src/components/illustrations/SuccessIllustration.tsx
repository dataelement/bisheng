import React from 'react';

/**
 * "Success" state illustration (checkmark badge).
 *
 * Per product decision this illustration FOLLOWS the brand theme (it is drawn
 * with the brand green #19B476 palette, not the semantic success green
 * #00b42a), so its greens re-point to `--brand-*` and turn blue in blue mode.
 * SVG presentation attributes ignore `var()`, so brand fills are set via inline
 * `style` (see BRAND-THEME-HANDOFF.md §3 / §5).
 *
 * Colour mapping (§5):
 *   #19B476 (main green)  → rgb(var(--brand-500))
 *   #BDE6D3 (light green) → rgb(var(--brand-100))
 *   white                 → kept as-is
 */
export const SuccessIllustration = ({ className, ...props }: React.SVGProps<SVGSVGElement>) => {
    const fill100 = { fill: 'rgb(var(--brand-100))' } as React.CSSProperties;
    const fill500 = { fill: 'rgb(var(--brand-500))' } as React.CSSProperties;

    return (
        <svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" className={className} {...props}>
            <path d="M88.6 102.042C89.6786 98.9983 93.9837 98.9983 95.0624 102.042L99.6562 115.007C100.001 115.982 100.768 116.748 101.742 117.093L114.707 121.687C117.751 122.766 117.751 127.071 114.707 128.15L101.742 132.743C100.768 133.089 100.001 133.855 99.6562 134.83L95.0624 147.794C93.9837 150.839 89.6786 150.839 88.6 147.794L84.0061 134.83C83.6609 133.855 82.8943 133.089 81.9198 132.743L68.9552 128.15C65.911 127.071 65.911 122.766 68.9551 121.687L81.9198 117.093C82.8943 116.748 83.6609 115.982 84.0061 115.007L88.6 102.042Z" style={fill500} />
            <path d="M124.798 96.9931C124.911 95.9225 126.307 95.588 126.893 96.491L129.261 100.138C129.448 100.427 129.756 100.616 130.099 100.652L134.423 101.109C135.494 101.222 135.828 102.618 134.925 103.204L131.278 105.572C130.989 105.759 130.8 106.067 130.764 106.41L130.307 110.734C130.194 111.805 128.798 112.139 128.212 111.236L125.845 107.589C125.657 107.3 125.349 107.111 125.006 107.075L120.682 106.618C119.611 106.505 119.277 105.109 120.18 104.523L123.827 102.156C124.116 101.968 124.305 101.66 124.341 101.317L124.798 96.9931Z" style={fill500} />
            <rect x="160.869" y="81.25" width="177.745" height="177.745" rx="88.8727" style={fill100} />
            <rect x="96.4115" y="107.568" width="213.682" height="213.682" rx="106.841" style={fill500} stroke="white" strokeWidth="8.02563" />
            <path d="M163.666 217.5L190.666 244L243.666 191" stroke="white" strokeWidth="16" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
};
