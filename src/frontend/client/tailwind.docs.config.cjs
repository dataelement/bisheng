/**
 * Tailwind config for the DOCS SITE only (rspress) — proves design-token.js is
 * consumable from a Tailwind `theme` field without touching the live app config.
 *
 * It imports the app's tailwind.config.cjs READ-ONLY and layers the SSOT's
 * `tailwindTheme` on top, so:
 *   • every existing app utility (blue-*, text-body, bg-fill-1 …) still works in demos;
 *   • the new SSOT-driven semantic utilities (text-text-title, bg-fill-hover …) exist too.
 *
 * The app's tailwind.config.cjs is unchanged; when the team is ready, the same two
 * lines (`require('./src/design-token')` + spread) can move into it verbatim.
 */
const app = require('./tailwind.config.cjs');
const { tailwindTheme, TEXT, FILL, BORDER, BG } = require('./src/design-token.cjs');

// Safelist the SSOT-driven semantic utilities so they always exist in the docs
// build (Tailwind JIT would otherwise only emit classes it literally finds in
// scanned source). This both guarantees the utilities are available to spec /
// demo authors and proves this config — not the app's — is the one running.
const safelist = [
  ...TEXT.map((t) => `text-text-${t.name}`),
  ...FILL.map((f) => `bg-fill-${f.name}`),
  ...BORDER.map((b) => `border-border-${b.name}`),
  ...BG.map((b) => `bg-bg-${b.name}`),
];

module.exports = {
  ...app,
  safelist,
  theme: {
    ...app.theme,
    extend: {
      ...app.theme.extend,
      colors: { ...app.theme.extend.colors, ...tailwindTheme.colors },
      fontSize: { ...app.theme.extend.fontSize, ...tailwindTheme.fontSize },
    },
  },
};
