import React from 'react';

/**
 * "No permission to access data" empty-state illustration (locked database).
 *
 * Brand greens re-point to the `--brand-*` palette so the illustration follows
 * the blue ⇄ green theme switch. SVG presentation attributes ignore `var()`,
 * so brand fills / strokes are applied via inline `style`
 * (see BRAND-THEME-HANDOFF.md §3).
 *
 * Colour mapping (§5):
 *   #19B476 (main green)  → rgb(var(--brand-500))
 *   #BDE6D3 (light green) → rgb(var(--brand-100))
 *   white                 → kept as-is
 */
export const NoPermissionIllustration = ({ className, ...props }: React.SVGProps<SVGSVGElement>) => {
    const fill100 = { fill: 'rgb(var(--brand-100))' } as React.CSSProperties;
    const fill500 = { fill: 'rgb(var(--brand-500))' } as React.CSSProperties;
    const stroke100 = { stroke: 'rgb(var(--brand-100))' } as React.CSSProperties;

    return (
        <svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" className={className} {...props}>
            <path d="M139 262V136.5C139 103.087 166.087 76 199.5 76C232.913 76 260 103.087 260 136.5V207.5" style={stroke100} strokeWidth="34" strokeLinecap="round" />
            <rect x="95.0232" y="152.981" width="208.977" height="151.299" rx="18.4818" style={fill500} stroke="white" strokeWidth="7.0235" />
            <rect x="233.5" y="203.5" width="116" height="116" rx="58" style={fill100} stroke="white" strokeWidth="7" />
            <circle cx="199" cy="221" r="24" fill="white" />
            <rect x="190" y="216" width="18" height="56" rx="9" fill="white" />
            <rect x="259" y="254" width="65" height="16" rx="8" style={fill500} />
        </svg>
    );
};
