// const { fontFamily } = require('tailwindcss/defaultTheme');
const plugin = require('tailwindcss/plugin');

/** @type {import('tailwindcss').Config} */
module.exports = {
  // 基础-多端适配原则.md §1: hover states are disabled on touch APP-WIDE — every
  // `hover:` utility compiles wrapped in a hover-capable media query. Press
  // feedback on touch comes from `active:` styles instead (no sticky hover).
  // NOTE: components must keep using plain `hover:` (never a custom variant),
  // so tailwind-merge can still dedupe business-page hover overrides.
  future: {
    hoverOnlyWhenSupported: true,
  },
  content: ['./src/**/*.{js,jsx,ts,tsx}'],
  // darkMode: 'class',
  darkMode: ['class'],
  theme: {
    fontFamily: {
      // font-family-base / font-family-mono in docs-ui-refactor/基础-字体规范.md §1.
      // Pure system stack, kept in sync with the global body/html rule in src/style.css
      // (that hardcoded rule is what actually sets the app-wide font; this config only
      // affects explicit font-sans / font-mono usages).
      sans: [
        '-apple-system',
        'BlinkMacSystemFont',
        '"Segoe UI"',
        'Roboto',
        '"PingFang SC"',
        '"Hiragino Sans GB"',
        '"Microsoft YaHei"',
        '"Noto Sans CJK SC"',
        'sans-serif',
      ],
      mono: ['ui-monospace', '"SF Mono"', '"Cascadia Mono"', 'Consolas', '"Liberation Mono"', 'monospace'],
    },
    // fontFamily: {
    //   sans: ['Söhne', 'sans-serif'],
    //   mono: ['Söhne Mono', 'monospace'],
    // },
    extend: {
      // Semantic type scale (docs-ui-refactor/基础-字体规范.md §2/§7) — MUST live in
      // `extend` so Tailwind's default text-xs/sm/base/... classes stay available
      // (900+ existing usages). Values reference semantic CSS vars defined in
      // src/style.css :root, which remap under 768px for the mobile ladder, so
      // classNames never change per breakpoint. Each entry carries its own
      // font-weight (400 body tier / 500 heading tier) — no extra font-medium needed.
      fontSize: {
        caption: ['var(--text-caption)', { lineHeight: 'var(--leading-caption)', fontWeight: '400' }],
        'body-sm': ['var(--text-body-sm)', { lineHeight: 'var(--leading-body-sm)', fontWeight: '400' }],
        body: ['var(--text-body)', { lineHeight: 'var(--leading-body)', fontWeight: '400' }],
        h4: ['var(--text-h4)', { lineHeight: 'var(--leading-h4)', fontWeight: '500' }],
        h3: ['var(--text-h3)', { lineHeight: 'var(--leading-h3)', fontWeight: '500' }],
        h2: ['var(--text-h2)', { lineHeight: 'var(--leading-h2)', fontWeight: '500' }],
        h1: ['var(--text-h1)', { lineHeight: 'var(--leading-h1)', fontWeight: '500' }],
        display: ['var(--text-display)', { lineHeight: 'var(--leading-display)', fontWeight: '500' }],
        metric: ['var(--text-metric)', { lineHeight: 'var(--leading-metric)', fontWeight: '500' }],
      },
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
        // Brand accent palette — re-pointed to CSS variables so the whole app's
        // existing `blue-*` utilities follow a single switchable theme (blue ⇄ green).
        // Channel-triplet form keeps Tailwind's `/<alpha>` opacity modifiers working.
        // Defaults (in style.css) match Tailwind's stock blue, so appearance is unchanged.
        'blue-main': 'rgb(var(--brand-main) / <alpha-value>)',
        blue: {
          50: 'rgb(var(--brand-50) / <alpha-value>)',
          100: 'rgb(var(--brand-100) / <alpha-value>)',
          200: 'rgb(var(--brand-200) / <alpha-value>)',
          300: 'rgb(var(--brand-300) / <alpha-value>)',
          400: 'rgb(var(--brand-400) / <alpha-value>)',
          500: 'rgb(var(--brand-500) / <alpha-value>)',
          600: 'rgb(var(--brand-600) / <alpha-value>)',
          700: 'rgb(var(--brand-700) / <alpha-value>)',
          800: 'rgb(var(--brand-800) / <alpha-value>)',
          900: 'rgb(var(--brand-900) / <alpha-value>)',
        },
        'brand-purple': '#ab68ff',
        // Button semantic tokens (docs-ui-refactor/组件-Button按钮.md §5.1) —
        // RGB-channel vars defined in src/style.css :root; channel form keeps
        // `/<alpha>` modifiers working. Neutral fill ramp is shared Arco grays.
        'btn-gray-text': 'rgb(var(--btn-gray-text) / <alpha-value>)',
        'btn-gray-border': 'rgb(var(--btn-gray-border) / <alpha-value>)',
        'btn-fill-1': 'rgb(var(--btn-fill-1) / <alpha-value>)',
        'btn-fill-2': 'rgb(var(--btn-fill-2) / <alpha-value>)',
        'btn-fill-3': 'rgb(var(--btn-fill-3) / <alpha-value>)',
        'btn-fill-4': 'rgb(var(--btn-fill-4) / <alpha-value>)',
        'btn-danger': 'rgb(var(--btn-danger) / <alpha-value>)',
        'btn-danger-hover': 'rgb(var(--btn-danger-hover) / <alpha-value>)',
        'btn-danger-active': 'rgb(var(--btn-danger-active) / <alpha-value>)',
        'btn-disabled-border': 'rgb(var(--btn-disabled-border) / <alpha-value>)',
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
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
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
      // Primary input: mouse + hover vs touch / coarse pointer (for hover-only controls).
      addVariant('fine-pointer', '@media (hover: hover) and (pointer: fine)');
      addVariant(
        'coarse-pointer',
        '@media not ((hover: hover) and (pointer: fine))',
      );
    }),
    // require('@tailwindcss/typography'),
  ],
};
