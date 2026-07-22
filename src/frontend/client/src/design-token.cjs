/**
 * design-token.js — Single Source of Truth (SSOT) for BiSheng client design tokens.
 *
 * ONE catalog, consumed by two audiences:
 *   • components  — via Tailwind (docs build spreads `tailwindTheme` into theme.extend;
 *                   the live app config can adopt the same import when the team migrates).
 *   • docs / md   — the spec .mdx pages and component demo pages import the catalogs
 *                   below and render every table / swatch straight from this file, so
 *                   the written spec can never drift from the values components ship.
 *
 * CommonJS (`module.exports`) on purpose: a `.cjs` Tailwind config can `require()` it,
 * and rspack/vite ESM-interop lets an .mdx page `import tokens from '~/design-token'`.
 *
 * ── Naming (req: no unclear numbered names) ──────────────────────────────────────────
 * Semantic tokens carry ROLE names (text-title / fill-hover …). The old numeric names
 * (text-1, fill-2 …) are kept as DEPRECATED `legacy` aliases so nothing breaks; the app
 * migrates to the role names gradually. See MIGRATION at the bottom for the full map.
 * Primitive ramps that are genuinely a scale (brand-50…900, gray-1…10) stay numbered —
 * that IS their semantic (lightness step), same convention as Tailwind's own palettes.
 *
 * ── Runtime behaviour ────────────────────────────────────────────────────────────────
 * Themeable / responsive tokens still resolve through CSS custom properties defined in
 * src/style.css (brand blue⇄green switch; ≤768px type remap). This file owns the token
 * NAMES + documented values and drives the Tailwind theme keys; the CSS vars remain the
 * runtime carrier. Regenerating :root from this file is a later step (app migration).
 */

/* ------------------------------------------------------------------ *
 * Typography — 基础-字体规范.md
 * ------------------------------------------------------------------ */

const FONT_FAMILY = {
  base: {
    token: 'font-family-base',
    cls: 'font-sans',
    usage: '全局默认（已写入 body/html，无需显式加类）',
    stack: [
      '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto',
      '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"',
      '"Noto Sans CJK SC"', 'sans-serif',
    ],
  },
  mono: {
    token: 'font-family-mono',
    cls: 'font-mono',
    usage: 'ID、代码、日志',
    stack: ['ui-monospace', '"SF Mono"', '"Cascadia Mono"', 'Consolas', '"Liberation Mono"', 'monospace'],
  },
};

/** Semantic type scale — each entry is a Tailwind fontSize key AND its own weight. */
const TYPE_SCALE = [
  { name: 'caption',  desktop: [12, 20], mobile: [12, 20], weight: 400, cssVar: '--text-caption',  leadingVar: '--leading-caption',  usage: '时间戳、标签、水印' },
  { name: 'body-sm',  desktop: [13, 21], mobile: [14, 22], weight: 400, cssVar: '--text-body-sm',  leadingVar: '--leading-body-sm',  usage: '密集表格、侧栏次要项' },
  { name: 'body',     desktop: [14, 22], mobile: [16, 24], weight: 400, cssVar: '--text-body',     leadingVar: '--leading-body',     usage: '正文基准，表单、表格默认' },
  { name: 'h4',       desktop: [16, 24], mobile: [16, 24], weight: 500, cssVar: '--text-h4',       leadingVar: '--leading-h4',       usage: '强调正文、四级标题' },
  { name: 'h3',       desktop: [18, 26], mobile: [17, 25], weight: 500, cssVar: '--text-h3',       leadingVar: '--leading-h3',       usage: '卡片标题' },
  { name: 'h2',       desktop: [20, 28], mobile: [18, 26], weight: 500, cssVar: '--text-h2',       leadingVar: '--leading-h2',       usage: '区块标题' },
  { name: 'h1',       desktop: [24, 32], mobile: [22, 30], weight: 500, cssVar: '--text-h1',       leadingVar: '--leading-h1',       usage: '页面标题' },
  { name: 'display',  desktop: [30, 38], mobile: [26, 34], weight: 500, cssVar: '--text-display',  leadingVar: '--leading-display',  usage: '大标题、营销场景' },
  { name: 'metric',   desktop: [36, 44], mobile: [30, 38], weight: 500, cssVar: '--text-metric',   leadingVar: '--leading-metric',   usage: 'Dashboard 核心指标数字' },
];

const FONT_WEIGHT = [
  { name: 'regular', token: 'font-weight-regular', cls: 'font-normal', value: 400, usage: '正文、说明' },
  { name: 'medium',  token: 'font-weight-medium',  cls: 'font-medium', value: 500, usage: '标题、强调、按钮' },
];

/* ------------------------------------------------------------------ *
 * Brand ramp — dual theme (基础-色彩规范.md §1). Documented hex per theme;
 * Tailwind resolves these through --brand-N so they switch blue⇄green at
 * runtime. Numbered because it is a lightness scale (that is the semantic).
 * ------------------------------------------------------------------ */

const BRAND_STEPS = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900'];

const BRAND = {
  main: '500',
  accentStep: '700', // darker shade used as the primary-marker accent bar
  role: {
    '50': '选中背景', '100': 'filled hover', '200': '触屏 active', '300': '过渡档',
    '400': 'hover 态', '500': '主色', '600': '按下 active', '700': '深色档',
    '800': '深色档', '900': '深色档', muted: '低饱和点缀',
  },
  blue:  { '50': '#E8F3FF', '100': '#BEDAFF', '200': '#94BFFF', '300': '#6AA1FF', '400': '#4080FF', '500': '#165DFF', '600': '#024DE3', '700': '#0239AB', '800': '#042B80', '900': '#051D52', muted: '#5773B4' },
  green: { '50': '#E4F1E7', '100': '#CCE4D2', '200': '#A3D2B0', '300': '#6FBA85', '400': '#3D9B5C', '500': '#169C47', '600': '#098B35', '700': '#076929', '800': '#074E20', '900': '#063216', muted: '#5C8A77' },
};

/* ------------------------------------------------------------------ *
 * Neutral primitive — Arco gray 1–10 (§2.1). Numbered = the lightness
 * scale itself; components consume the semantic layer below, not this.
 * `channels` = "r g b" for rgb(var(--arco-gray-N)/α).
 * `darkHex` / `darkChannels` = official @arco-design/color gray.dark ramp
 * (lightness inverts). Runtime carrier: `.dark` override in src/style.css.
 * ------------------------------------------------------------------ */

const GRAY = [
  { n: 1,  hex: '#F7F8FA', channels: '247 248 250', darkHex: '#17171A', darkChannels: '23 23 26',    role: 'hover 底' },
  { n: 2,  hex: '#F2F3F5', channels: '242 243 245', darkHex: '#2E2E30', darkChannels: '46 46 48',    role: 'filled 底' },
  { n: 3,  hex: '#E5E6EB', channels: '229 230 235', darkHex: '#484849', darkChannels: '72 72 73',    role: '边框' },
  { n: 4,  hex: '#C9CDD4', channels: '201 205 212', darkHex: '#5F5F60', darkChannels: '95 95 96',    role: '禁用 / 占位' },
  { n: 5,  hex: '#A9AEB8', channels: '169 174 184', darkHex: '#78787A', darkChannels: '120 120 122', role: '过渡' },
  { n: 6,  hex: '#86909C', channels: '134 144 156', darkHex: '#929293', darkChannels: '146 146 147', role: '辅助文字' },
  { n: 7,  hex: '#6B7785', channels: '107 119 133', darkHex: '#ABABAC', darkChannels: '171 171 172', role: '过渡' },
  { n: 8,  hex: '#4E5969', channels: '78 89 105',   darkHex: '#C5C5C5', darkChannels: '197 197 197', role: '次文字' },
  { n: 9,  hex: '#272E3B', channels: '39 46 59',    darkHex: '#DFDFDF', darkChannels: '223 223 223', role: '过渡' },
  { n: 10, hex: '#1D2129', channels: '29 33 41',    darkHex: '#F6F6F6', darkChannels: '246 246 246', role: '主文字' },
];

/* ------------------------------------------------------------------ *
 * Semantic layer (§2.2) — ROLE names (canonical) + numeric `legacy` alias.
 * `cssVar` is the existing runtime carrier in src/style.css.
 * ------------------------------------------------------------------ */

// Role names avoid the taken shadcn keys (text-primary/secondary/tertiary);
// intensity ramp strong → muted → hint → disabled maps gray-10 → 8 → 6 → 4.
// `hex` = light value; `darkHex` = same gray ref resolved on the dark ramp.
const TEXT = [
  { name: 'strong',    legacy: '1', cssVar: '--text-1', ref: 'gray-10', hex: '#1D2129', darkHex: '#F6F6F6', usage: '主文字：标题、正文主体' },
  { name: 'muted',     legacy: '2', cssVar: '--text-2', ref: 'gray-8',  hex: '#4E5969', darkHex: '#C5C5C5', usage: '次要文字：次要说明、默认按钮文字' },
  { name: 'hint',      legacy: '3', cssVar: '--text-3', ref: 'gray-6',  hex: '#86909C', darkHex: '#929293', usage: '辅助文字：弱提示、时间戳、占位符' },
  { name: 'disabled',  legacy: '4', cssVar: '--text-4', ref: 'gray-4',  hex: '#C9CDD4', darkHex: '#5F5F60', usage: '禁用文字' },
];

const FILL = [
  { name: 'subtle',  legacy: '1', cssVar: '--fill-1', ref: 'gray-1', hex: '#F7F8FA', darkHex: '#17171A', usage: '浅填充：hover 底、页面浅灰背景' },
  { name: 'default', legacy: '2', cssVar: '--fill-2', ref: 'gray-2', hex: '#F2F3F5', darkHex: '#2E2E30', usage: '填充：active 底、filled 控件底' },
  { name: 'hover',   legacy: '3', cssVar: '--fill-3', ref: 'gray-3', hex: '#E5E6EB', darkHex: '#484849', usage: '深填充：filled hover' },
  { name: 'active',  legacy: '4', cssVar: '--fill-4', ref: 'gray-4', hex: '#C9CDD4', darkHex: '#5F5F60', usage: '重填充：filled active' },
];

const BORDER = [
  { name: 'base', cssVar: '--border-base', ref: 'gray-3', hex: '#E5E6EB', darkHex: '#484849', usage: '常规边框：输入框、卡片、分割线' },
  { name: 'deep', cssVar: '--border-deep', ref: 'gray-4', hex: '#C9CDD4', darkHex: '#5F5F60', usage: '深边框：强调分割、hover 边框' },
];

/* Background surfaces — the "white that darkens" family. The gray ramp starts
 * at gray-1 (#F7F8FA), so the pure page surface needs its own semantic token
 * (the fixed `--white: #fff` legacy var never theme-flips — different job).
 * Carrier: --bg-page in src/style.css (:root + .dark override). */
const BG = [
  { name: 'page', cssVar: '--bg-page', hex: '#FFFFFF', darkHex: '#121212', usage: '页面底色：内容区、顶栏等最底层表面' },
];

/* ------------------------------------------------------------------ *
 * Functional colors (§3) — fixed hex, never theme-switched.
 * ------------------------------------------------------------------ */

const FUNCTIONAL = [
  { name: 'success', label: '成功 Success', cssVar: '--success', main: '#00B42A', hover: '#23C343', active: '#009A29', tint: '#E8FFEA' },
  { name: 'warning', label: '警告 Warning', cssVar: '--warning', main: '#FF7D00', hover: '#FF9A2E', active: '#D25F00', tint: '#FFF7E8' },
  { name: 'danger',  label: '危险 Danger',  cssVar: '--danger',  main: '#F53F3F', hover: '#D6373A', active: '#D02F33', tint: '#FFECE8' },
];

/* ------------------------------------------------------------------ *
 * Tag pairs (§4) — light bg + strong text. Purple / approving-blue are
 * intentional fixed exceptions (not tokenized, never theme-switched).
 * ------------------------------------------------------------------ */

const TAG = [
  { label: '技能（紫 · 未 token 化）', bg: '#F5E8FF', fg: '#722ED1', note: '固定例外色' },
  { label: '助手（橙 = warning 同值）', bg: '#FFF7E8', fg: '#FF7D00', note: 'warning tint' },
  { label: '已完成',                   bg: '#E8FFEA', fg: '#00B42A', note: 'success tint' },
  { label: '已驳回',                   bg: '#FFECE8', fg: '#F53F3F', note: 'danger tint' },
  { label: '审批中（例外：永远蓝）',    bg: '#E8F3FF', fg: '#165DFF', note: '固定蓝，不换肤' },
];

/* ------------------------------------------------------------------ *
 * Radius (01-设计规范.md §1) & icon sizes (基础-图标规范.md §3.2)
 * ------------------------------------------------------------------ */

/* Radius ladder aligns 1:1 with Tailwind's own scale (sm…4xl + full) so the
 * class name IS the token name. sm/md/lg derive from --radius (8px base) in
 * tailwind.config; xl/2xl/3xl are Tailwind defaults; 4xl (32px) is our extend.
 * Off-scale legacy values (rounded-[5px]/[10px]/[20px]…) fold into the
 * nearest step when touched. */
const RADIUS = [
  { name: 'sm',   px: 4,    usage: 'small 控件 / 标签 / 表格行内按钮' },
  { name: 'md',   px: 6,    usage: 'medium 控件（默认）：按钮、输入框、菜单项' },
  { name: 'lg',   px: 8,    usage: 'large 控件 / --radius 基准 / 消息气泡' },
  { name: 'xl',   px: 12,   usage: '卡片、下拉面板 Popover' },
  { name: '2xl',  px: 16,   usage: '弹窗 / 大卡片容器' },
  { name: '3xl',  px: 24,   usage: '抽屉、超大容器' },
  { name: '4xl',  px: 32,   usage: '特大容器 / hero 区块' },
  { name: 'full', px: 9999, usage: '胶囊 / 圆形：头像、圆形图标按钮、pill 标签' },
];

const ICON_SIZE = [
  { name: 'xs',  px: 12, strokeWidth: 2.5, usage: '极小标记（badge、密集表格角标），仅纯展示' },
  { name: 'sm',  px: 14, usage: 'small / medium 按钮的文字+icon' },
  { name: 'md',  px: 16, usage: '默认：图标按钮、菜单项、输入框内、表格操作' },
  { name: 'lg',  px: 20, usage: '导航栏、侧边栏入口、页头操作' },
  { name: 'xl',  px: 24, usage: '独立展示、弹窗标题图标（原始画布尺寸）' },
  { name: 'xl2', px: 32, strokeWidth: 1.5, usage: '超大展示：空状态、引导页' },
];

/* ================================================================== *
 * Derived: Tailwind theme fragment — spread into theme.extend.
 * Channel-triplet form keeps `/<alpha>` opacity modifiers working.
 * ================================================================== */

const withAlpha = (cssVar) => `rgb(var(${cssVar}) / <alpha-value>)`;

/** Color keys embed their category (text-/fill-/border-) so a single utility reads right. */
const colors = {};
TEXT.forEach((t) => {
  colors[`text-${t.name}`] = withAlpha(t.cssVar); // canonical role name
  colors[`text-${t.legacy}`] = withAlpha(t.cssVar); // DEPRECATED alias (kept for migration)
});
FILL.forEach((f) => {
  colors[`fill-${f.name}`] = withAlpha(f.cssVar);
  colors[`fill-${f.legacy}`] = withAlpha(f.cssVar); // DEPRECATED alias
});
BORDER.forEach((b) => {
  colors[`border-${b.name}`] = withAlpha(b.cssVar);
});
BG.forEach((b) => {
  colors[`bg-${b.name}`] = withAlpha(b.cssVar); // class: bg-bg-page
});
FUNCTIONAL.forEach((fn) => {
  colors[fn.name] = {
    DEFAULT: withAlpha(fn.cssVar),
    hover: withAlpha(`${fn.cssVar}-hover`),
    active: withAlpha(`${fn.cssVar}-active`),
    tint: withAlpha(`${fn.cssVar}-tint`),
  };
});

const fontSize = {};
TYPE_SCALE.forEach((s) => {
  fontSize[s.name] = [`var(${s.cssVar})`, { lineHeight: `var(${s.leadingVar})`, fontWeight: String(s.weight) }];
});

const tailwindTheme = { colors, fontSize };

/* ================================================================== *
 * Migration map — old numeric class → new role class, for the app's
 * gradual adoption (both resolve identically until the old alias is
 * removed). Emitted as data so tooling / codemods can read it.
 * ================================================================== */

const MIGRATION = [
  ...TEXT.map((t) => ({ from: `text-text-${t.legacy}`, to: `text-text-${t.name}`, cssVar: t.cssVar })),
  ...FILL.map((f) => ({ from: `bg-fill-${f.legacy}`,   to: `bg-fill-${f.name}`,   cssVar: f.cssVar })),
];

module.exports = {
  FONT_FAMILY,
  TYPE_SCALE,
  FONT_WEIGHT,
  BRAND,
  BRAND_STEPS,
  GRAY,
  TEXT,
  FILL,
  BORDER,
  BG,
  FUNCTIONAL,
  TAG,
  RADIUS,
  ICON_SIZE,
  tailwindTheme,
  MIGRATION,
};
