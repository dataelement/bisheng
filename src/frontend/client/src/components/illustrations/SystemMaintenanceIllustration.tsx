import React from 'react';

/**
 * "System maintenance" empty-state illustration (database with a wrench).
 *
 * Brand greens re-point to the `--brand-*` palette so the illustration follows
 * the blue ⇄ green theme switch. SVG presentation attributes ignore `var()`,
 * so brand fills / strokes are applied via inline `style`
 * (see BRAND-THEME-HANDOFF.md §3).
 *
 * Colour mapping (§5):
 *   #19B476 (main green)  → rgb(var(--illus-500))
 *   #BDE6D3 (light green) → rgb(var(--illus-100))
 *   white                 → kept as-is
 */
export const SystemMaintenanceIllustration = ({ className, grey, ...props }: React.SVGProps<SVGSVGElement> & { grey?: boolean }) => {
    const fill100 = { fill: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const fill500 = { fill: 'rgb(var(--illus-500))' } as React.CSSProperties;

    return (
        <svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" className={['brand-illustration', grey && 'illus-grey', className].filter(Boolean).join(' ')} {...props}>
            <ellipse cx="181.687" cy="155.079" rx="106.687" ry="23.8642" style={fill500} />
            <rect x="74.9999" y="100.332" width="213.374" height="55.2151" style={fill500} />
            <circle cx="99.7018" cy="143.766" r="10.266" fill="white" />
            <circle opacity="0.6" cx="129.04" cy="149.766" r="10.266" fill="white" />
            <ellipse cx="181.687" cy="99.8642" rx="106.687" ry="23.8642" style={fill500} stroke="white" strokeWidth="8" />
            <path d="M288.374 223.864H288.352C287.237 236.828 239.909 247.26 181.686 247.26C123.464 247.26 76.1366 236.828 75.0224 223.864H74.9999V168.649H75.0224C76.1372 181.613 123.464 192.046 181.686 192.046C239.909 192.046 287.237 181.613 288.352 168.649H288.374V223.864Z" style={fill100} />
            <path d="M288.374 292.181H288.352C287.238 305.145 239.91 315.577 181.686 315.577C123.464 315.577 76.1364 305.145 75.0224 292.181H74.9999V236.966H75.0224C76.137 249.93 123.464 260.363 181.686 260.363C239.909 260.363 287.237 249.93 288.352 236.966H288.374V292.181Z" style={fill100} />
            <path d="M174.2 223.925C174.2 251.9 197.034 274.639 224.982 274.521C228.553 274.507 232.035 274.124 235.386 273.404C238.486 272.742 241.719 273.712 243.967 275.963L285.169 317.205C289.694 321.735 295.66 324 301.626 324C307.592 324 313.557 321.735 318.083 317.205C322.609 312.675 324.872 306.703 324.872 300.732C324.872 294.76 322.609 288.788 318.083 284.258L276.778 242.913C274.545 240.678 273.575 237.456 274.222 234.368C274.927 231.014 275.294 227.528 275.294 223.969C275.324 196.067 252.622 173.328 224.747 173.328C221.103 173.328 217.547 173.711 214.109 174.446C213.198 174.637 212.287 174.858 211.39 175.108C207.923 176.064 206.776 180.418 209.318 182.977L211.317 184.977L234.724 208.393C238.104 211.776 239.97 216.306 239.97 221.16C239.97 225.999 238.104 230.529 234.724 233.912C231.345 237.295 226.819 239.163 221.985 239.163C217.15 239.163 212.625 237.295 209.23 233.912L183.839 208.481C181.297 205.937 176.933 207.069 175.978 210.555C175.728 211.452 175.508 212.364 175.317 213.276C174.582 216.718 174.2 220.277 174.2 223.925Z" style={fill500} stroke="white" strokeWidth="8" />
            <circle opacity="0.4" cx="99.7018" cy="210.766" r="10.266" fill="white" />
            <circle opacity="0.4" cx="99.7018" cy="277.766" r="10.266" fill="white" />
        </svg>
    );
};
