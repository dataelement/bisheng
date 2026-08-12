import React from 'react';

/**
 * "Something went wrong" illustration (a mechanic holding a wrench), for the
 * route error boundary. Distinct from SystemMaintenanceIllustration, which
 * stays as it is for the backend-down overlay.
 *
 * Brand greens re-point to the `--illus-*` palette so the illustration follows
 * the blue ⇄ green theme switch (and greyscale via the `grey` prop). SVG
 * presentation attributes ignore `var()`, so brand fills / strokes are applied
 * via inline `style` (see BRAND-THEME-HANDOFF.md §3 / §3.1).
 *
 * Colour mapping (by lightness → §5):
 *   #19B476 (main green)           → rgb(var(--illus-500))
 *   #AAE9CE (cheek accents)        → rgb(var(--illus-300))
 *   #D3EFE3 / #DDF0E8 (light)      → rgb(var(--illus-100))
 *   white                          → kept as-is
 *
 * The cheek accents are the one place the light greens are not folded together:
 * they are drawn on the white face rather than over the green body, and at the
 * 100 step they all but disappear against it.
 *
 * The viewBox is the design's own 120x120 board and the figure keeps the offset
 * it was drawn at, so the illustration carries its own breathing room; call
 * sites size the box from the outside.
 */
export const SystemErrorIllustration = ({ className, grey, ...props }: React.SVGProps<SVGSVGElement> & { grey?: boolean }) => {
    const fill100 = { fill: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const fill500 = { fill: 'rgb(var(--illus-500))' } as React.CSSProperties;
    const stroke100 = { stroke: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const stroke300 = { stroke: 'rgb(var(--illus-300))' } as React.CSSProperties;
    const stroke500 = { stroke: 'rgb(var(--illus-500))' } as React.CSSProperties;
    const fill500stroke500 = { fill: 'rgb(var(--illus-500))', stroke: 'rgb(var(--illus-500))' } as React.CSSProperties;

    return (
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" className={['brand-illustration', grey && 'illus-grey', className].filter(Boolean).join(' ')} {...props}>
            <g transform="translate(20.791 19.51)">
                <circle cx="40.2841" cy="44.1724" r="33.2104" style={fill100} />
                <ellipse cx="40.3575" cy="77.4911" rx="35.2662" ry="2.53031" style={fill100} />
                <path d="M60.8431 52.8487C63.2217 60.8538 63.7922 68.4341 64.1642 76.2541H19.7255L18.6185 67.5561L13.5579 69.2957C7.82567 68.906 6.20299 66.9832 5.49253 61.2303C5.79936 55.2088 8.30262 52.5029 18.6185 49.3695C24.361 44.9092 28.1884 42.9875 39.3355 43.6763C51.1378 43.6208 56.6693 44.7471 60.8431 52.8487Z" style={fill500stroke500} strokeWidth="0.316289" />
                <path d="M47.2427 57.4566C43.0865 62.4493 39.2591 64.1324 27.1583 62.9916L24.4699 71.6896C36.8527 75.0328 43.8536 76.2176 57.2058 63.7824" style={stroke100} strokeWidth="1.89774" strokeLinecap="round" />
                <circle cx="42.4292" cy="29.554" r="23.6526" fill="white" style={stroke500} strokeWidth="1.89774" />
                <path d="M12.237 31.1817C11.6525 29.5941 12.987 27.9472 14.6706 28.2159L14.6715 28.2149C14.8871 28.2491 15.1013 28.2915 15.3112 28.339L15.3102 28.3399C16.0938 28.5143 16.8674 28.7714 17.6208 29.1163C23.4114 31.767 25.9618 38.6441 23.3043 44.4356L23.3053 44.4366C22.968 45.1735 22.5597 45.8614 22.0934 46.4923L22.0944 46.4933C21.9846 46.6422 21.9448 46.8364 21.9879 47.0206L22.0114 47.0987L22.027 47.1388L22.0397 47.1808L29.7711 73.3868C30.3193 74.9176 30.2027 76.5335 29.5739 77.9073C28.9359 79.3011 27.7654 80.4607 26.2155 81.0382C24.6654 81.6156 23.022 81.5041 21.6286 80.8663C20.2351 80.2284 19.0766 79.0576 18.5006 77.5069L18.486 77.4659L18.4733 77.4239L10.7633 51.2892C10.6816 51.0937 10.5139 50.9526 10.317 50.9083C9.55057 50.739 8.79097 50.4877 8.05044 50.1524C2.23335 47.5193 -0.346392 40.6276 2.31313 34.8175C2.65872 34.0625 3.07622 33.3604 3.5563 32.7149C3.6834 32.5429 3.81776 32.372 3.95767 32.2061C5.02397 30.9379 7.02078 31.2546 7.68032 32.7188L7.73989 32.8634V32.8643L10.2819 39.713L10.3756 39.9317C10.6177 40.4264 11.0196 40.8199 11.5368 41.0567C12.1284 41.3275 12.7754 41.3499 13.3688 41.129C13.9622 40.9079 14.438 40.4672 14.7096 39.8741C14.9827 39.2776 15.0051 38.6294 14.7848 38.0362L12.2379 31.1856L12.237 31.1817Z" style={fill500} stroke="white" strokeWidth="2.53031" />
                <circle cx="23.8373" cy="66.1545" r="6.95836" fill="white" style={stroke100} strokeWidth="1.58145" />
                <circle cx="17.1952" cy="64.573" r="6.95836" fill="white" style={stroke100} strokeWidth="1.58145" />
                <path d="M55.8637 3.9663C68.2802 10.0967 70.9643 24.0879 67.561 34.9999C64.7606 31.2684 60.6109 27.7843 55.8637 24.7829C43.8116 17.1632 27.9076 12.6552 20.4491 15.1113C14.4695 12.9324 17.0687 9.18294 25.4852 9.73155C33.3147 1.69381 43.4472 -2.16408 55.8637 3.9663Z" style={fill500} />
                <path d="M25.4852 9.73155C33.3147 1.69381 43.4472 -2.16408 55.8637 3.9663C68.2802 10.0967 70.9643 24.0879 67.561 34.9999C64.7606 31.2684 60.6109 27.7843 55.8637 24.7829M25.4852 9.73155C17.0687 9.18294 14.4695 12.9324 20.4491 15.1113C27.9076 12.6552 43.8116 17.1632 55.8637 24.7829M25.4852 9.73155C45.4981 12.1173 52.3212 17.9861 55.8637 24.7829" style={stroke100} strokeWidth="1.89774" strokeLinecap="round" strokeLinejoin="round" />
                <ellipse cx="32.0119" cy="27.2021" rx="1.58145" ry="2.37217" transform="rotate(10.0939 32.0119 27.2021)" style={fill500} />
                <ellipse cx="47.6078" cy="30.0813" rx="1.58145" ry="2.37217" transform="rotate(8.53515 47.6078 30.0813)" style={fill500} />
                <path d="M43.3981 37.592C39.4348 38.3137 37.4544 37.9148 34.1674 36.397C34.1674 36.397 34.1184 41.9966 38.6506 42.3041C43.1828 42.6116 43.3981 37.592 43.3981 37.592Z" style={fill500stroke500} strokeWidth="1.26516" strokeLinejoin="round" />
                <path d="M51.8029 36.6694L51.163 38.2744M49.621 36.5435L49.1405 37.9307M53.6458 37.3498L53.2461 38.2611" style={stroke300} strokeWidth="1.20677" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M26.0587 31.5815L25.4188 33.1865M27.9016 32.2619L27.5019 33.1732" style={stroke300} strokeWidth="1.20677" strokeLinecap="round" strokeLinejoin="round" />
            </g>
        </svg>
    );
};
