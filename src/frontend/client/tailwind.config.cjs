/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS Tailwind config: require() is the only import form available here */
// const { fontFamily } = require('tailwindcss/defaultTheme');
const plugin = require('tailwindcss/plugin');

/** @type {import('tailwindcss').Config} */
module.exports = {
  // The design system (type scale, semantic colors, radius/shadow/z tiers, the
  // motion keyframes, `darkMode`, `hoverOnlyWhenSupported` and the pointer
  // variants) comes from @bisheng/ui — ONE definition shared with the library's
  // own components, so a token can no longer mean two things in two configs.
  // Anything below is client-only: keep app-specific keys here, and add a
  // cross-app one to the preset instead of re-declaring it here.
  presets: [require('@bisheng/ui/tailwind-preset')],
  // packages/ui is source-shipped: its classes must be scanned here too,
  // or shared components (e.g. @bisheng/ui Button) lose their styles.
  content: ['./src/**/*.{js,jsx,ts,tsx}', '../packages/ui/src/**/*.{ts,tsx}'],
  theme: {
    // fontFamily: {
    //   sans: ['Söhne', 'sans-serif'],
    //   mono: ['Söhne Mono', 'monospace'],
    // },
    extend: {
      width: {
        authPageWidth: '370px',
      },
      keyframes: {
        'accordion-down': {
          from: { height: 0 },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: 0 },
        },
        'pulse-scale': {
          '0%, 100%': { transform: 'scale(0.6)' },
          '50%': { transform: 'scale(1)' },
        },
        'crawl-slide': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(400%)' },
        },
        // Linsight thinking line entrance: fade in + slide up slightly.
        'thinking-appear': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // Linsight narration ticker (R2): the incoming complete sentence rolls up
        // into place, but stays INVISIBLE for the first half so it never overlaps
        // the outgoing one (no ghost / double-image during the slide).
        'narration-in': {
          '0%': { opacity: '0', transform: 'translateY(55%)' },
          '50%': { opacity: '0', transform: 'translateY(28%)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        // The outgoing sentence fades FULLY by the midpoint, then keeps sliding up
        // (already invisible) — so there is no frame where both lines are visible.
        'narration-out': {
          '0%': { opacity: '1', transform: 'translateY(0)' },
          '50%': { opacity: '0', transform: 'translateY(-28%)' },
          '100%': { opacity: '0', transform: 'translateY(-55%)' },
        },
        // diagonal glint sweeping continuously across the subagent card
        'sheen-sweep': {
          '0%': { transform: 'translateX(-130%)' },
          '100%': { transform: 'translateX(130%)' },
        },
        // highlight sweeping through a running label (gradient clipped to text).
        // Travel = exactly one tile (200%, matching bg-[length:200%_100%]) so the
        // highlight crosses ONCE per cycle and the loop is seamless.
        'text-shimmer': {
          '0%': { backgroundPosition: '200% 0' },
          '100%': { backgroundPosition: '0% 0' },
        },
        // Share login handoff: a dot runs the track and comes BACK, because the
        // login trip is a round trip (we return the user to the shared page).
        // Paired with animation-direction: alternate — hence 0%→100% only.
        'return-trace': {
          '0%': { left: '0%' },
          '100%': { left: '100%' },
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out forwards',
        'crawl-slide': 'crawl-slide 1.4s linear infinite',
        'sheen-sweep': 'sheen-sweep 2s linear infinite',
        'text-shimmer': 'text-shimmer 3.2s linear infinite',
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
        'pulse-scale': 'pulse-scale 1s ease-in-out infinite',
        'thinking-appear': 'thinking-appear 0.25s ease-out',
        // Slower, calmer handoff; staggered opacity keyframes do the no-overlap work.
        'narration-in': 'narration-in 0.5s ease-out',
        'narration-out': 'narration-out 0.5s ease-in forwards',
        // `alternate` is what encodes "round trip" — do not switch to a plain loop.
        'return-trace': 'return-trace 1.6s ease-in-out infinite alternate',
      },
      colors: {
        gray: {
          20: '#ececf1',
          50: '#f7f7f8',
          100: '#ececec',
          200: '#e3e3e3',
          300: '#cdcdcd',
          400: '#999696',
          500: '#595959',
          600: '#424242',
          700: '#2f2f2f',
          800: '#212121',
          850: '#171717',
          900: '#0d0d0d',
        },
        green: {
          50: '#f1f9f7',
          100: '#def2ed',
          200: '#a6e5d6',
          300: '#6dc8b9',
          400: '#41a79d',
          500: '#10a37f',
          550: '#349072',
          600: '#126e6b',
          700: '#0a4f53',
          800: '#06373e',
          900: '#031f29',
        },
        'brand-purple': '#ab68ff',
        'presentation': 'var(--presentation)',
        'text-primary': 'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'text-secondary-alt': 'var(--text-secondary-alt)',
        'text-tertiary': 'var(--text-tertiary)',
        'ring-primary': 'var(--ring-primary)',
        'header-primary': 'var(--header-primary)',
        'header-hover': 'var(--header-hover)',
        'header-button-hover': 'var(--header-button-hover)',
        'surface-active': 'var(--surface-active)',
        'surface-active-alt': 'var(--surface-active-alt)',
        'surface-hover': 'var(--surface-hover)',
        'surface-hover-alt': 'var(--surface-hover-alt)',
        'surface-primary': 'var(--surface-primary)',
        'surface-primary-alt': 'var(--surface-primary-alt)',
        'surface-primary-contrast': 'var(--surface-primary-contrast)',
        'surface-secondary': 'var(--surface-secondary)',
        'surface-secondary-alt': 'var(--surface-secondary-alt)',
        'surface-tertiary': 'var(--surface-tertiary)',
        'surface-tertiary-alt': 'var(--surface-tertiary-alt)',
        'surface-dialog': 'var(--surface-dialog)',
        'surface-submit': 'var(--surface-submit)',
        'surface-submit-hover': 'var(--surface-submit-hover)',
        'surface-destructive': 'var(--surface-destructive)',
        'surface-destructive-hover': 'var(--surface-destructive-hover)',
        'border-light': 'var(--border-light)',
        'border-medium': 'var(--border-medium)',
        'border-medium-alt': 'var(--border-medium-alt)',
        'border-heavy': 'var(--border-heavy)',
        'border-xheavy': 'var(--border-xheavy)',
        /* These are test styles */
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ['switch-unchecked']: 'hsl(var(--switch-unchecked))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        // Tailwind's ladder ends at 3xl (24px); the spec's largest container
        // step is 32px (design-token.cjs RADIUS) — extend so it has a class.
        '4xl': '2rem',
      },
    },
  },
  plugins: [
    require('tailwindcss-animate'),
    require('tailwindcss-radix')(),
    plugin(({ addVariant }) => {
      // Viewport breakpoints (align with Tailwind `lg` at 1024px).
      addVariant('touch-desktop', '@media (min-width: 1024px)');
      addVariant('touch-mobile', '@media (max-width: 1023px)');
      // 订阅文章列表等：平板窄宽 — 搜索与信息源/未读筛选同一行
      addVariant(
        'range-576-768',
        '@media (min-width: 576px) and (max-width: 768px)',
      );
      addVariant('lt-576', '@media (max-width: 575px)');
    }),
    // require('@tailwindcss/typography'),
  ],
};
