"""Standalone not-found page artwork and layout overrides.

The SVG mirrors AppUnpublishedIllustration.tsx in packages/ui so app-proxy
can render it without fetching frontend assets. Keep the geometry in sync.
"""

ILLUSTRATION = """
<svg width="120" height="120" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" style="color:rgb(var(--bg-page))">
<defs>
<path id="app-unpublished-badge" d="M115.162 321.178C146.732 321.178 172.324 295.586 172.324 264.016C172.324 232.446 146.732 206.854 115.162 206.854C83.5923 206.854 58 232.446 58 264.016C58 295.586 83.5923 321.178 115.162 321.178Z" />
<path id="app-unpublished-left-plug" d="M80.8648 252.583H96.4544V283.763H80.8648C75.6682 283.763 72.5503 279.606 72.5503 274.409V261.937C72.5503 256.741 75.6682 252.583 80.8648 252.583Z" />
<path id="app-unpublished-right-plug" d="M136.988 242.19H148.42C153.617 242.19 156.735 246.348 156.735 251.544V264.016C156.735 269.212 153.617 273.37 148.42 273.37H136.988V242.19Z" />
<mask id="app-unpublished-badge-mask" maskUnits="userSpaceOnUse" x="50" y="198.854" width="130" height="130">
<rect fill="white" x="50" y="198.854" width="130" height="130" />
<use href="#app-unpublished-badge" fill="black" />
</mask>
<mask id="app-unpublished-left-plug-mask">
<use href="#app-unpublished-left-plug" fill="white" />
</mask>
<mask id="app-unpublished-right-plug-mask">
<use href="#app-unpublished-right-plug" fill="white" />
</mask>
</defs>
<path d="M220.22 301.608L297.849 256.904C301.299 255.185 303.024 251.746 303.024 248.307V158.899L225.395 203.603C222.414 205.221 222.377 205.221 220.182 206.333L220.22 301.608ZM308.199 131.389C316.825 136.547 322 145.144 322 153.741V248.307C322 258.623 316.825 267.22 308.199 270.659L225.395 317.082C216.769 322.24 206.419 322.24 199.518 317.082L116.714 270.659C108.088 265.501 102.913 256.904 102.913 248.307V153.741C102.913 143.425 108.088 134.828 116.714 131.389L199.518 84.9659C208.144 79.8077 218.494 79.8077 225.395 84.9659L308.199 131.389Z" style="fill:rgb(var(--illus-100))" />
<use href="#app-unpublished-badge" style="fill:rgb(var(--illus-500))" />
<use href="#app-unpublished-badge" stroke-width="14.5503" stroke="currentColor" mask="url(#app-unpublished-badge-mask)" />
<path d="M67.354 268.173H79.8257" stroke-width="8.31448" stroke-linecap="round" stroke="currentColor" />
<use href="#app-unpublished-left-plug" fill="currentColor" />
<use href="#app-unpublished-left-plug" stroke-width="2.07862" stroke="currentColor" mask="url(#app-unpublished-left-plug-mask)" />
<path d="M96.4546 259.859H104.769M96.4546 276.488H104.769" stroke-width="5.19655" stroke-linecap="round" stroke="currentColor" />
<path d="M152.577 257.78H164.01" stroke-width="8.31448" stroke-linecap="round" stroke="currentColor" />
<use href="#app-unpublished-right-plug" fill="currentColor" />
<use href="#app-unpublished-right-plug" stroke-width="2.07862" stroke="currentColor" mask="url(#app-unpublished-right-plug-mask)" />
<path d="M128.673 249.466H136.987M128.673 266.095H136.987" stroke-width="5.19655" stroke-linecap="round" stroke="currentColor" />
<path d="M116.201 230.758V238.033" stroke-width="8.31448" stroke-linecap="round" stroke="currentColor" />
<path d="M115.162 291.558V298.833" stroke-width="8.31448" stroke-linecap="round" stroke="currentColor" />
</svg>
"""

# Match the maintenance overlay's outlined action and the StateView mobile tier.
STYLE = """
:root {
  --btn-gray-text: 82 88 101;
  --btn-fill-1: 248 248 248;
  --btn-fill-2: 243 243 244;
}
a.button {
  border: 1px solid rgb(var(--border-base));
  background: rgb(var(--bg-page)); color: rgb(var(--btn-gray-text));
}
@media (hover: hover) {
  a.button:hover { background: rgb(var(--btn-fill-1)); }
}
@media (pointer: coarse) {
  a.button { min-height: 44px; }
  a.button:active { background: rgb(var(--btn-fill-2)); }
}
@media (max-width: 768px) {
  a.button { width: 100%; }
}
@media (prefers-color-scheme: dark) {
  :root {
    --btn-gray-text: 197 197 197;
    --btn-fill-1: 38 38 40;
    --btn-fill-2: 46 46 48;
  }
}
"""
