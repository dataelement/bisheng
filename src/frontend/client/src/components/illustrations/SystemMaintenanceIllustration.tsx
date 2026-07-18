import React from 'react';

/**
 * "System maintenance" empty-state illustration (magnifier over a bug).
 *
 * Brand greens re-point to the `--illus-*` palette so the illustration follows
 * the blue ⇄ green theme switch (and greyscale via the `grey` prop). SVG
 * presentation attributes ignore `var()`, so brand fills / strokes are applied
 * via inline `style` (see BRAND-THEME-HANDOFF.md §3 / §3.1 / §3.2).
 *
 * Colour mapping (by lightness → §5):
 *   #19B476 (main green)           → rgb(var(--illus-500))
 *   #86DEB8 / #9BDDC1 (mid green)  → rgb(var(--illus-300))
 *   #D3EFE3 / #DDF0E8 / #AAE9CE    → rgb(var(--illus-100))
 *   white                          → kept as-is
 */
export const SystemMaintenanceIllustration = ({ className, grey, ...props }: React.SVGProps<SVGSVGElement> & { grey?: boolean }) => {
    const fill100 = { fill: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const fill300 = { fill: 'rgb(var(--illus-300))' } as React.CSSProperties;
    const fill500 = { fill: 'rgb(var(--illus-500))' } as React.CSSProperties;
    const stroke100 = { stroke: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const stroke500 = { stroke: 'rgb(var(--illus-500))' } as React.CSSProperties;
    const fill500stroke100 = { fill: 'rgb(var(--illus-500))', stroke: 'rgb(var(--illus-100))' } as React.CSSProperties;
    const fill500stroke500 = { fill: 'rgb(var(--illus-500))', stroke: 'rgb(var(--illus-500))' } as React.CSSProperties;

    return (
        <svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" className={['brand-illustration', grey && 'illus-grey', className].filter(Boolean).join(' ')} {...props}>
            <circle cx="199.564" cy="221.492" r="108.508" style={fill100} />
            <path d="M243.805 97.0672C256.64 98.1625 269.476 111.673 269.476 111.673L255.838 135.406C255.838 135.406 232.173 126.643 226.959 118.245C221.745 109.847 230.97 95.972 243.805 97.0672Z" style={fill100} />
            <ellipse cx="205.881" cy="320.8" rx="120.4" ry="8.4" style={fill100} />
            <path d="M271.87 111.073C292.15 125.045 299.901 132.12 309.359 143.163L310.37 144.35L310.444 144.466C316.432 153.778 318.847 158.829 320.744 166.031L321.117 167.501L321.137 167.579L321.149 167.658C322.551 176.134 322.797 182.534 321.075 187.921C319.323 193.403 315.639 197.528 309.915 201.696L309.913 201.697C294.721 212.726 286.298 217.232 271.588 223.492C266.991 225.946 264.556 227.745 263.36 229.389C262.39 230.723 262.14 232.093 262.611 234.248L262.715 234.69L262.729 234.746C270.058 267.8 270.337 286.463 268.374 319.724L268.258 321.697H141.853L142.38 319.171C148.247 291.094 149.949 275.296 147.146 246.201C146.534 239.856 148.962 234.358 153.559 229.468C158.101 224.636 164.842 220.302 173.137 216.115C189.702 207.752 213.298 199.582 239.922 189.245L240.067 189.189L240.219 189.155C252.964 186.277 260.574 184.368 279.163 177.77C283.174 173.991 284.684 171.529 284.979 169.557C285.262 167.671 284.508 165.69 282.273 162.559C269.863 150.168 262.48 145.109 249.113 136.141L247.647 135.158L248.366 133.546C250.757 128.184 252.837 123.78 255.999 120.097C259.211 116.356 263.422 113.48 269.894 110.857L270.94 110.433L271.87 111.073Z" style={fill500stroke100} strokeWidth="4.19355" />
            <ellipse cx="199.564" cy="209.96" rx="29.879" ry="25.6855" fill="white" />
            <circle cx="176.681" cy="148.4" r="78.4" fill="white" style={stroke500} strokeWidth="6.29032" />
            <path d="M124.08 138.608C124.629 141.427 122.79 144.158 119.971 144.707C117.152 145.257 114.422 143.417 113.872 140.599C113.322 137.78 115.807 129.625 116.985 129.396C118.163 129.166 123.53 135.789 124.08 138.608Z" style={fill300} />
            <path d="M208.879 99.4077C209.429 102.226 207.59 104.957 204.771 105.507C201.952 106.056 199.221 104.217 198.672 101.398C198.122 98.5794 200.607 90.4248 201.785 90.1952C202.963 89.9655 208.33 96.5889 208.879 99.4077Z" style={fill300} />
            <path d="M229.68 129.808C230.229 132.627 228.39 135.357 225.571 135.907C222.752 136.457 220.022 134.617 219.472 131.798C218.922 128.98 221.407 120.825 222.585 120.595C223.763 120.366 229.13 126.989 229.68 129.808Z" style={fill300} />
            <path d="M126.171 134.625C126.635 137.006 125.081 139.313 122.699 139.778C120.318 140.242 118.01 138.688 117.546 136.306C117.082 133.925 119.181 127.035 120.177 126.841C121.172 126.647 125.706 132.243 126.171 134.625Z" fill="white" />
            <path d="M211.002 95.5828C211.475 98.0081 209.892 100.358 207.467 100.83C205.041 101.303 202.692 99.7207 202.219 97.2954C201.746 94.8701 203.884 87.854 204.898 87.6564C205.911 87.4588 210.529 93.1575 211.002 95.5828Z" fill="white" />
            <path d="M231.78 125.875C232.248 128.27 230.684 130.591 228.289 131.058C225.894 131.525 223.573 129.962 223.106 127.566C222.639 125.171 224.751 118.241 225.752 118.046C226.753 117.851 231.313 123.479 231.78 125.875Z" fill="white" />
            <path d="M170.54 261.855C171.74 285.855 169.664 295.588 166.54 319.055" style={stroke100} strokeWidth="6.29032" strokeLinecap="round" />
            <ellipse cx="141.207" cy="165.992" rx="3.77185" ry="7.33871" transform="rotate(73.507 141.207 165.992)" style={fill500} />
            <ellipse cx="177.424" cy="159.413" rx="7.355" ry="3.63321" transform="rotate(-9.93375 177.424 159.413)" style={fill500} />
            <path d="M179.573 179.108C167.9 185.591 161.258 186.446 149.325 185.179C149.325 185.179 155.13 202.809 169.684 198.952C184.239 195.094 179.573 179.108 179.573 179.108Z" style={fill500stroke500} strokeWidth="4.19355" strokeLinejoin="round" />
            <path d="M134.701 185.323L133.501 190.923M127.501 186.123L126.701 189.723" style={stroke100} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M205.991 168.548L204.791 174.148M198.791 169.348L197.991 174.148M212.391 169.748L211.591 172.948" style={stroke100} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="101.081" cy="255.2" r="13.2" style={fill500} />
            <path d="M81.904 237.37C81.904 240.639 79.2589 243.288 75.9959 243.288C72.733 243.288 70.0879 240.639 70.0879 237.37C70.0879 234.101 72.733 231.452 75.9959 231.452C79.2589 231.452 81.904 234.101 81.904 237.37Z" style={fill300} />
            <path d="M299.685 277.953C299.685 281.221 297.04 283.871 293.777 283.871C290.514 283.871 287.869 281.221 287.869 277.953C287.869 274.684 290.514 272.034 293.777 272.034C297.04 272.034 299.685 274.684 299.685 277.953Z" style={fill300} />
            <circle cx="285.481" cy="89.1999" r="5.6" style={fill500} />
        </svg>
    );
};
