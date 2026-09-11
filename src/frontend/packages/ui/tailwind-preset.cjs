const plugin = require('tailwindcss/plugin');

/**
 * @bisheng/ui tailwind preset — maps the semantic tokens in
 * `src/styles/tokens.css` to Tailwind classes. Consumers add:
 *
 *   presets: [require('@bisheng/ui/tailwind-preset')],
 *   content: [..., '../packages/ui/src/** / *.{ts,tsx}']
 *
 * Values are seeded verbatim from client/tailwind.config.cjs so adopting the
 * preset changes nothing visually. Keep the two in sync until client fully
 * migrates onto the preset (then delete the duplicated keys there).
 *
 * @type {Partial<import('tailwindcss').Config>}
 */
module.exports = {
  // 多端适配原则 §1: hover states are disabled on touch APP-WIDE — every
  // `hover:` utility compiles wrapped in a hover-capable media query.
  // Components keep using plain `hover:` (never a custom variant) so
  // tailwind-merge can still dedupe overrides.
  future: {
    hoverOnlyWhenSupported: true,
  },
  darkMode: ['class'],
  theme: {
    fontFamily: {
      // 基础-字体规范.md §1 — pure system stack.
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
    extend: {
      // Semantic type scale (基础-字体规范.md §2/§7) — values reference the
      // semantic CSS vars in tokens.css, which remap under 768px, so
      // classNames never change per breakpoint.
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
      colors: {
        // Brand accent — channel-triplet vars keep `/<alpha>` modifiers working;
        // the whole app's `blue-*` utilities follow the blue ⇄ green theme switch.
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
        // Page surface: white in light, #121212 in dark.
        'bg-page': 'rgb(var(--bg-page) / <alpha-value>)',
        // Button semantic tokens (组件-Button按钮.md §5.1)
        'btn-gray-text': 'rgb(var(--btn-gray-text) / <alpha-value>)',
        'btn-gray-solid-bg': 'rgb(var(--btn-gray-solid-bg) / <alpha-value>)',
        'btn-gray-border': 'rgb(var(--btn-gray-border) / <alpha-value>)',
        'btn-fill-1': 'rgb(var(--btn-fill-1) / <alpha-value>)',
        'btn-fill-2': 'rgb(var(--btn-fill-2) / <alpha-value>)',
        'btn-fill-3': 'rgb(var(--btn-fill-3) / <alpha-value>)',
        'btn-fill-4': 'rgb(var(--btn-fill-4) / <alpha-value>)',
        'btn-danger': 'rgb(var(--btn-danger) / <alpha-value>)',
        'btn-danger-hover': 'rgb(var(--btn-danger-hover) / <alpha-value>)',
        'btn-danger-active': 'rgb(var(--btn-danger-active) / <alpha-value>)',
        'btn-disabled-border': 'rgb(var(--btn-disabled-border) / <alpha-value>)',
        'btn-disabled-bg': 'rgb(var(--btn-disabled-bg) / <alpha-value>)',
        'btn-disabled-text': 'rgb(var(--btn-disabled-text) / <alpha-value>)',
        // Arco semantic layer (基础-色彩规范.md §2/§3/§7) — primitives are
        // intentionally NOT wired so components can't bypass semantic names.
        'text-1': 'rgb(var(--text-1) / <alpha-value>)',
        'text-2': 'rgb(var(--text-2) / <alpha-value>)',
        'text-3': 'rgb(var(--text-3) / <alpha-value>)',
        'text-4': 'rgb(var(--text-4) / <alpha-value>)',
        'fill-1': 'rgb(var(--fill-1) / <alpha-value>)',
        'fill-2': 'rgb(var(--fill-2) / <alpha-value>)',
        'fill-3': 'rgb(var(--fill-3) / <alpha-value>)',
        'fill-4': 'rgb(var(--fill-4) / <alpha-value>)',
        'border-base': 'rgb(var(--border-base) / <alpha-value>)',
        'border-deep': 'rgb(var(--border-deep) / <alpha-value>)',
        success: {
          DEFAULT: 'rgb(var(--success) / <alpha-value>)',
          hover: 'rgb(var(--success-hover) / <alpha-value>)',
          active: 'rgb(var(--success-active) / <alpha-value>)',
          tint: 'rgb(var(--success-tint) / <alpha-value>)',
        },
        warning: {
          DEFAULT: 'rgb(var(--warning) / <alpha-value>)',
          hover: 'rgb(var(--warning-hover) / <alpha-value>)',
          active: 'rgb(var(--warning-active) / <alpha-value>)',
          tint: 'rgb(var(--warning-tint) / <alpha-value>)',
        },
        danger: {
          DEFAULT: 'rgb(var(--danger) / <alpha-value>)',
          hover: 'rgb(var(--danger-hover) / <alpha-value>)',
          active: 'rgb(var(--danger-active) / <alpha-value>)',
          tint: 'rgb(var(--danger-tint) / <alpha-value>)',
        },
      },
      // Radius token scale (rounded-md/lg used by Button sizes: 6/8px).
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
    },
  },
  plugins: [
    plugin(({ addVariant }) => {
      // Primary input: mouse + hover vs touch / coarse pointer.
      addVariant('fine-pointer', '@media (hover: hover) and (pointer: fine)');
      addVariant('coarse-pointer', '@media not ((hover: hover) and (pointer: fine))');
    }),
  ],
};
