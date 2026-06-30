import React, { useId } from 'react';

/**
 * "Crawling in progress" status illustration (magnifier over a document list).
 *
 * Brand greens re-point to the `--brand-*` palette so the illustration follows
 * the blue ⇄ green theme switch. SVG presentation attributes ignore `var()`,
 * so brand fills / strokes are applied via inline `style`. The mask `id` is
 * uniquified with `useId()` so multiple instances on one page don't collide
 * (see BRAND-THEME-HANDOFF.md §3).
 *
 * Colour mapping (§5):
 *   #19B476 (main green)  → rgb(var(--illus-500))
 *   #BDE6D3 (light green) → rgb(var(--illus-100))
 *   #7CD0B1 (mid green)   → rgb(var(--illus-300))
 *   white                 → kept as-is
 */
export const CrawlingIllustration = ({ className, grey, ...props }: React.SVGProps<SVGSVGElement> & { grey?: boolean }) => {
    const uid = useId();
    const maskId = `crawling-mask-${uid}`;

    const fill100 = { fill: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const fill500 = { fill: 'rgb(var(--illus-500))' } as React.CSSProperties;
    const fill300 = { fill: 'rgb(var(--illus-300))' } as React.CSSProperties;
    const lens = { fill: 'rgb(var(--illus-500))', stroke: 'rgb(var(--illus-500))' } as React.CSSProperties;

    return (
        <svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" className={['brand-illustration', grey && 'illus-grey', className].filter(Boolean).join(' ')} {...props}>
            <rect x="93.0688" y="93.8433" width="242.448" height="175.532" rx="19.3958" style={fill100} />
            <rect x="52.6884" y="131.953" width="242.448" height="175.532" rx="19.3958" style={fill500} stroke="white" strokeWidth="7.37691" />
            <path d="M91.5182 176.03H207.893" stroke="white" strokeWidth="12" strokeLinecap="round" />
            <path opacity="0.7" d="M91.5182 209.322H140.008" stroke="white" strokeWidth="12" strokeLinecap="round" />
            <mask id={maskId} maskUnits="userSpaceOnUse" x="191.511" y="162.615" width="183.181" height="190.914" fill="black">
                <rect fill="white" x="191.511" y="162.615" width="183.181" height="190.914" />
                <path d="M238.1 202.51C257.616 186.727 286.233 189.752 302.017 209.269C315.707 226.197 315.242 249.968 302.144 266.277L329.112 299.622C332.48 303.787 331.834 309.894 327.67 313.263C323.505 316.631 317.397 315.986 314.028 311.821L287.06 278.476C268.373 287.873 245.031 283.355 231.341 266.427C215.557 246.911 218.583 218.294 238.1 202.51Z" />
            </mask>
            <path d="M238.1 202.51C257.616 186.727 286.233 189.752 302.017 209.269C315.707 226.197 315.242 249.968 302.144 266.277L329.112 299.622C332.48 303.787 331.834 309.894 327.67 313.263C323.505 316.631 317.397 315.986 314.028 311.821L287.06 278.476C268.373 287.873 245.031 283.355 231.341 266.427C215.557 246.911 218.583 218.294 238.1 202.51Z" style={fill300} />
            <path d="M238.1 202.51L233.155 196.396L233.155 196.396L238.1 202.51ZM302.017 209.269L308.131 204.324L308.131 204.324L302.017 209.269ZM302.144 266.277L296.013 261.353L292.045 266.294L296.03 271.222L302.144 266.277ZM327.67 313.263L332.614 319.377L332.615 319.377L327.67 313.263ZM287.06 278.476L293.175 273.531L289.189 268.603L283.528 271.45L287.06 278.476ZM231.341 266.427L225.226 271.372L225.227 271.372L231.341 266.427ZM238.1 202.51L243.044 208.624C259.184 195.572 282.85 198.074 295.902 214.214L302.017 209.269L308.131 204.324C289.616 181.431 256.048 177.882 233.155 196.396L238.1 202.51ZM302.017 209.269L295.902 214.214C307.217 228.204 306.845 247.867 296.013 261.353L302.144 266.277L308.275 271.201C323.64 252.07 324.196 224.189 308.131 204.324L302.017 209.269ZM302.144 266.277L296.03 271.222L322.998 304.567L329.112 299.622L335.226 294.677L308.259 261.332L302.144 266.277ZM329.112 299.622L322.998 304.567C323.635 305.355 323.513 306.511 322.724 307.149L327.67 313.263L332.615 319.377C340.156 313.278 341.326 302.22 335.226 294.677L329.112 299.622ZM327.67 313.263L322.725 307.149C321.936 307.787 320.779 307.664 320.142 306.876L314.028 311.821L307.914 316.766C314.014 324.309 325.073 325.476 332.614 319.377L327.67 313.263ZM314.028 311.821L320.142 306.876L293.175 273.531L287.06 278.476L280.946 283.421L307.914 316.766L314.028 311.821ZM287.06 278.476L283.528 271.45C268.075 279.221 248.77 275.473 237.455 261.482L231.341 266.427L225.227 271.372C241.292 291.237 268.672 296.525 290.593 285.501L287.06 278.476ZM231.341 266.427L237.455 261.482C224.402 245.343 226.905 221.677 243.044 208.624L238.1 202.51L233.155 196.396C210.261 214.911 206.712 248.479 225.226 271.372L231.341 266.427Z" fill="white" mask={`url(#${maskId})`} />
            <path d="M247.884 214.61C260.719 204.23 279.537 206.22 289.916 219.054C300.296 231.888 298.306 250.707 285.472 261.086C272.637 271.465 253.819 269.476 243.44 256.641C233.06 243.807 235.05 224.989 247.884 214.61Z" style={lens} strokeWidth="7.8636" />
        </svg>
    );
};
