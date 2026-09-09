import React from 'react';

/**
 * "Article Q&A" empty-state illustration (chat bubbles with a checkmark).
 *
 * Brand greens re-point to the `--brand-*` palette so the illustration follows
 * the blue ⇄ green theme switch. SVG presentation attributes ignore `var()`,
 * so brand fills are applied via inline `style` (see BRAND-THEME-HANDOFF.md §3).
 *
 * Colour mapping (§5):
 *   #19B476 (main green)  → rgb(var(--illus-500))
 *   #BDE6D3 (light green) → rgb(var(--illus-100))
 *   white                 → kept as-is
 */
export const ArticleQAIllustration = ({ className, grey, ...props }: React.SVGProps<SVGSVGElement> & { grey?: boolean }) => {
    const fill100 = { fill: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const fill500 = { fill: 'rgb(var(--illus-500))' } as React.CSSProperties;

    return (
        <svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" className={['brand-illustration', grey && 'illus-grey', className].filter(Boolean).join(' ')} {...props}>
            <path d="M145 219.5L172 246L225 193" stroke="white" strokeWidth="16" strokeLinecap="round" strokeLinejoin="round" />
            <rect x="43" y="90" width="204" height="138" rx="24" style={fill500} />
            <path opacity="0.4" d="M138 172H208.5" stroke="white" strokeWidth="12" strokeLinecap="round" />
            <path opacity="0.4" d="M138 148H182" stroke="white" strokeWidth="12" strokeLinecap="round" />
            <path d="M116.864 185.178L109.734 191.192L103.472 183.938C100.661 185.095 97.6027 185.674 94.296 185.674C89.7493 185.674 85.7813 184.641 82.392 182.574C79.044 180.507 76.4607 177.573 74.642 173.77C72.8233 169.926 71.914 165.421 71.914 160.254C71.914 155.087 72.8233 150.603 74.642 146.8C76.4607 142.956 79.044 140.001 82.392 137.934C85.7813 135.867 89.7493 134.834 94.296 134.834C98.8427 134.834 102.79 135.867 106.138 137.934C109.527 140.001 112.131 142.956 113.95 146.8C115.769 150.603 116.678 155.087 116.678 160.254C116.678 164.015 116.182 167.425 115.19 170.484C114.239 173.543 112.834 176.188 110.974 178.42L116.864 185.178ZM81.524 160.254C81.524 163.602 82.0407 166.537 83.074 169.058C84.1073 171.538 85.5953 173.46 87.538 174.824C89.4807 176.188 91.7333 176.87 94.296 176.87C96.8587 176.87 99.1113 176.188 101.054 174.824C102.997 173.46 104.485 171.538 105.518 169.058C106.551 166.537 107.068 163.602 107.068 160.254C107.068 156.865 106.551 153.93 105.518 151.45C104.485 148.929 102.997 146.986 101.054 145.622C99.1527 144.258 96.9 143.576 94.296 143.576C91.692 143.576 89.4187 144.258 87.476 145.622C85.5747 146.986 84.1073 148.929 83.074 151.45C82.0407 153.93 81.524 156.865 81.524 160.254Z" fill="white" />
            <rect x="126.5" y="164.5" width="211" height="145" rx="27.5" style={fill100} stroke="white" strokeWidth="7" />
            <path d="M226 248H296.5" stroke="white" strokeWidth="12" strokeLinecap="round" />
            <path d="M226 224H270" stroke="white" strokeWidth="12" strokeLinecap="round" />
            <path d="M205.128 261.806H195.208L190.992 249.654H173.756L169.54 261.806H159.62L177.6 212.702H187.21L205.128 261.806ZM182.188 225.164L176.794 240.85H187.954L182.56 225.164H182.188Z" fill="white" />
            <path d="M76 228H105L86.2426 246.757C82.4628 250.537 76 247.86 76 242.515V228Z" style={fill500} />
            <path d="M299 306H270L288.757 324.757C292.537 328.537 299 325.86 299 320.515V306Z" style={fill100} />
        </svg>
    );
};
