"""Standalone unavailable page artwork and layout overrides.

The SVG mirrors AppInaccessibleIllustration.tsx in packages/ui so app-proxy
can render it without fetching frontend assets. Keep the geometry in sync.
"""

ILLUSTRATION = """
<svg width="120" height="120" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" style="color:rgb(var(--bg-page))">
<path d="M199 321C276.872 321 340 315.627 340 309C340 302.373 276.872 297 199 297C121.128 297 58 302.373 58 309C58 315.627 121.128 321 199 321Z" style="fill:rgb(var(--illus-100))" />
<path d="M188.087 284.299L258.953 243.49C262.102 241.921 263.677 238.781 263.677 235.642V154.024L192.811 194.833C190.09 196.31 190.056 196.31 188.053 197.325L188.087 284.299ZM268.402 128.91C276.276 133.619 281 141.467 281 149.315V235.642C281 245.06 276.276 252.908 268.402 256.047L192.811 298.426C184.937 303.135 175.488 303.135 169.189 298.426L93.5984 256.047C85.7244 251.338 81 243.49 81 235.642V149.315C81 139.898 85.7244 132.05 93.5984 128.91L169.189 86.5316C177.063 81.8228 186.512 81.8228 192.811 86.5316L268.402 128.91Z" style="fill:rgb(var(--illus-500))" />
<path d="M292 285L320 313" stroke-width="24" stroke-linecap="round" stroke="currentColor" />
<path d="M292 285L320 313" stroke-width="14" stroke-linecap="round" style="stroke:rgb(var(--illus-500))" />
<path d="M265.5 308C294.495 308 318 284.495 318 255.5C318 226.505 294.495 203 265.5 203C236.505 203 213 226.505 213 255.5C213 284.495 236.505 308 265.5 308Z" fill="currentColor" />
<path d="M265.5 300C290.077 300 310 280.077 310 255.5C310 230.923 290.077 211 265.5 211C240.923 211 221 230.923 221 255.5C221 280.077 240.923 300 265.5 300Z" stroke-width="7" style="fill:rgb(var(--illus-100));stroke:rgb(var(--illus-500))" />
<path d="M246 256H284" stroke-width="9" stroke-linecap="round" style="stroke:rgb(var(--illus-500))" />
</svg>
"""

# Use the maintenance overlay's spacing and text treatment for diagnostic details.
STYLE = """
.hint {
  margin-top: 16px; padding-top: 0; border-top: 0;
  font-size: 14px; line-height: 22px; font-weight: 500;
  color: rgb(var(--text-1) / 0.8);
}
.hint-id {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-weight: 400; color: rgb(var(--text-3));
}
"""
