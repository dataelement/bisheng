/**
 * Color section — visualizes the color spec from docs-ui-refactor/基础-色彩规范.md
 * (brand dual-theme ramp / Arco neutral grays / functional colors / tag pairs)
 * so the designer can verify the tokens landed in src/style.css + tailwind.config.cjs.
 *
 * DEV-ONLY internal tooling, never shipped (route gated by import.meta.env.DEV).
 * NOTE on literal hex values in this file: they are DISPLAY-ONLY spec swatches —
 * the blue and green brand columns must render side by side regardless of the
 * active theme, and some tag colors (skill purple, the fixed-blue exception) are
 * intentionally not tokenized. Business code must never hardcode these values.
 */
import { CSSProperties, ReactNode } from 'react';
import { cn } from '~/utils';
import { ComponentPage, ExampleGroup, ExampleGrid, ExampleCard, CompareTable } from '../components/kit';

/* ------------------------------------------------------------------ *
 * Small presentational helpers
 * ------------------------------------------------------------------ */

/** Inline swatch + optional code label, for table cells. */
function ColorCell({
  hex,
  className,
  style,
  label,
}: {
  /** Literal display color (spec documentation value). */
  hex?: string;
  /** Live token class (e.g. bg-blue-500) — proves the wiring works. */
  className?: string;
  style?: CSSProperties;
  label?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn('inline-block h-6 w-10 shrink-0 rounded border border-black/10', className)}
        style={hex ? { background: hex } : style}
      />
      {(label ?? hex) && (
        <code className="whitespace-nowrap text-caption text-muted-foreground">{label ?? hex}</code>
      )}
    </div>
  );
}

/** A light-bg + strong-text tag chip (§4 tag pairs). */
function TagChip({
  className,
  style,
  children,
}: {
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <span className={cn('inline-flex items-center rounded px-2 py-0.5 text-body-sm', className)} style={style}>
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ *
 * antd-style vertical palette column (基础色板 look): seamless stacked
 * swatches, step + hex overlaid, contrasting text, primary shade marked.
 * ------------------------------------------------------------------ */

/** Perceived-luminance pick of a readable overlay text color for a hex bg. */
function overlayText(hex: string): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? 'rgba(0,0,0,0.85)' : 'rgba(255,255,255,0.95)';
}

interface Swatch {
  /** Shade label shown on the left (step number, or 'muted'). */
  label: string;
  /** Documentation hex — used for the overlaid value AND text-contrast math. */
  hex: string;
  /** Optional live background (e.g. rgb(var(--arco-gray-N))); defaults to hex. */
  bg?: string;
  /** Mark this shade as the primary (主色). */
  primary?: boolean;
  /** Bottom-accent color for the primary marker (a darker shade of the ramp). */
  accent?: string;
  /** Purpose text — revealed on hover as a tooltip. */
  usage?: string;
}

/**
 * Horizontal palette strip — tall, flat, sharp-cornered, seamless. Each swatch
 * carries its own info (role / step / hex); hovering lifts it (scale + shadow,
 * still square-cornered), no tooltip, no caption line.
 */
function PaletteRow({ title, swatches }: { title?: ReactNode; swatches: Swatch[] }) {
  return (
    <div>
      {title && <div className="mb-3 text-body-sm font-medium text-text-primary">{title}</div>}
      <div className="flex">
        {swatches.map((s) => {
          const fg = overlayText(s.hex);
          return (
            <div
              key={s.label}
              className="group relative flex h-36 min-w-0 flex-1 cursor-default flex-col justify-between p-3.5 transition-transform duration-200 ease-out hover:z-10 hover:scale-[1.06] hover:shadow-2xl"
              style={{ background: s.bg ?? s.hex, color: fg }}
            >
              {/* role — hidden by default, fades in on hover (arco-style clean default) */}
              {s.usage && (
                <span
                  className="text-[11px] leading-snug opacity-0 transition-opacity duration-200 group-hover:opacity-100"
                  style={{ color: fg }}
                >
                  {s.usage}
                </span>
              )}
              <div>
                <div className={cn('text-body-sm leading-tight', s.primary && 'font-medium')}>
                  {s.label}
                </div>
                <div className="mt-1 font-mono text-caption leading-none" style={{ opacity: 0.8 }}>
                  {s.hex}
                </div>
              </div>
              {/* primary marker — a thin bottom accent bar in a darker shade of the ramp */}
              {s.primary && (
                <span className="absolute inset-x-0 bottom-0 h-[3px]" style={{ background: s.accent ?? fg }} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Spec data
 * ------------------------------------------------------------------ */

/** §1.1 brand ramp — blue/green documentation values. */
const BRAND_RAMP = [
  { step: '50', blue: '#E8F3FF', green: '#E4F1E7', usage: '浅底一档：选中背景；按钮 filled 底 / outlined·text hover' },
  { step: '100', blue: '#BEDAFF', green: '#CCE4D2', usage: '浅底二档：filled hover / outlined·text 触屏 active' },
  { step: '200', blue: '#94BFFF', green: '#A3D2B0', usage: '浅底三档：filled 触屏 active' },
  { step: '300', blue: '#6AA1FF', green: '#6FBA85', usage: '浅色过渡档 · 暂无固定用途' },
  { step: '400', blue: '#4080FF', green: '#3D9B5C', usage: 'hover（比主色亮一档）' },
  { step: '500', blue: '#165DFF', green: '#169C47', usage: '主色（= --brand-main）' },
  { step: '600', blue: '#024DE3', green: '#098B35', usage: 'active / 按下（深一档）' },
  { step: '700', blue: '#0239AB', green: '#076929', usage: '深色档 · 暂无固定用途' },
  { step: '800', blue: '#042B80', green: '#074E20', usage: '深色档 · 暂无固定用途' },
  { step: '900', blue: '#051D52', green: '#063216', usage: '深色档 · 暂无固定用途' },
];

/** §2.1 primitive Arco gray ramp — rendered live from --arco-gray-N. */
const ARCO_GRAYS = [
  { n: 1, hex: '#F7F8FA', note: 'hover 底 → fill-1' },
  { n: 2, hex: '#F2F3F5', note: 'filled 控件底 → fill-2' },
  { n: 3, hex: '#E5E6EB', note: '常规边框 → border-base / fill-3' },
  { n: 4, hex: '#C9CDD4', note: '禁用/占位 → text-4 / fill-4 / border-deep' },
  { n: 5, hex: '#A9AEB8', note: '中间档 · 无 semantic 映射' },
  { n: 6, hex: '#86909C', note: '辅助文字 → text-3（全站最高频 hex ×263）' },
  { n: 7, hex: '#6B7785', note: '中间档 · 无 semantic 映射' },
  { n: 8, hex: '#4E5969', note: '次要文字 → text-2' },
  { n: 9, hex: '#272E3B', note: '中间档 · 无 semantic 映射' },
  { n: 10, hex: '#1D2129', note: '主文字 → text-1' },
];

/** Concise in-card role labels (the palette shows these, not the verbose usage). */
const BRAND_ROLE: Record<string, string> = {
  '50': '选中背景',
  '100': 'filled hover',
  '200': '触屏 active',
  '300': '过渡档',
  '400': 'hover 态',
  '500': '主色',
  '600': '按下 active',
  '700': '深色档',
  '800': '深色档',
  '900': '深色档',
  muted: '低饱和点缀',
};

const ARCO_ROLE: Record<number, string> = {
  1: 'hover 底',
  2: 'filled 底',
  3: '边框',
  4: '禁用 / 占位',
  5: '过渡',
  6: '辅助文字',
  7: '过渡',
  8: '次文字',
  9: '过渡',
  10: '主文字',
};

/** §2.2 semantic neutral layer — token / class / value / live demo. */
const NEUTRAL_SEMANTIC: { token: string; cls: string; value: string; usage: string; demo: ReactNode }[] = [
  { token: '--text-1', cls: 'text-text-1', value: 'gray-10 #1D2129', usage: '主文字：标题、正文主体', demo: <span className="text-body text-text-1">标题、正文主体</span> },
  { token: '--text-2', cls: 'text-text-2', value: 'gray-8 #4E5969', usage: '次文字：次要说明、默认按钮文字', demo: <span className="text-body text-text-2">次要说明文字</span> },
  { token: '--text-3', cls: 'text-text-3', value: 'gray-6 #86909C', usage: '辅助文字：弱提示、时间戳、占位符', demo: <span className="text-body text-text-3">弱提示 · 10 分钟前</span> },
  { token: '--text-4', cls: 'text-text-4', value: 'gray-4 #C9CDD4', usage: '禁用文字', demo: <span className="text-body text-text-4">禁用状态文字</span> },
  { token: '--fill-1', cls: 'bg-fill-1', value: 'gray-1 #F7F8FA', usage: '浅填充：hover 底、页面浅灰背景', demo: <ColorCell className="bg-fill-1" /> },
  { token: '--fill-2', cls: 'bg-fill-2', value: 'gray-2 #F2F3F5', usage: '填充：active 底、filled 控件底', demo: <ColorCell className="bg-fill-2" /> },
  { token: '--fill-3', cls: 'bg-fill-3', value: 'gray-3 #E5E6EB', usage: '深填充：filled hover', demo: <ColorCell className="bg-fill-3" /> },
  { token: '--fill-4', cls: 'bg-fill-4', value: 'gray-4 #C9CDD4', usage: '重填充：filled active', demo: <ColorCell className="bg-fill-4" /> },
  { token: '--border-base', cls: 'border-border-base', value: 'gray-3 #E5E6EB', usage: '常规边框：输入框、卡片、分割线（规范里的 border）', demo: <span className="inline-block h-8 w-24 rounded-md border border-border-base bg-white" /> },
  { token: '--border-deep', cls: 'border-border-deep', value: 'gray-4 #C9CDD4', usage: '深边框：强调分割、hover 边框', demo: <span className="inline-block h-8 w-24 rounded-md border border-border-deep bg-white" /> },
];

/** Functional colors — fixed hex (不换肤); 主色 marked with a darker (active) accent. */
const FUNCTIONAL: { title: string; swatches: Swatch[] }[] = [
  {
    title: '成功 Success',
    swatches: [
      { label: '主色', hex: '#00B42A', primary: true, accent: '#009A29', usage: 'bg-success' },
      { label: 'hover', hex: '#23C343', usage: 'bg-success-hover' },
      { label: 'active', hex: '#009A29', usage: 'bg-success-active' },
      { label: 'tint 浅底', hex: '#E8FFEA', usage: 'bg-success-tint' },
    ],
  },
  {
    title: '警告 Warning',
    swatches: [
      { label: '主色', hex: '#FF7D00', primary: true, accent: '#D25F00', usage: 'bg-warning' },
      { label: 'hover', hex: '#FF9A2E', usage: 'bg-warning-hover' },
      { label: 'active', hex: '#D25F00', usage: 'bg-warning-active' },
      { label: 'tint 浅底', hex: '#FFF7E8', usage: 'bg-warning-tint' },
    ],
  },
  {
    title: '危险 Danger',
    swatches: [
      { label: '主色', hex: '#F53F3F', primary: true, accent: '#D02F33', usage: 'bg-danger' },
      { label: 'hover', hex: '#D6373A', usage: 'bg-danger-hover' },
      { label: 'active', hex: '#D02F33', usage: 'bg-danger-active' },
      { label: 'tint 浅底', hex: '#FFECE8', usage: 'bg-danger-tint（仅 tag）' },
    ],
  },
  {
    title: '链接 / 信息 Info（= 品牌色，跟随主题）',
    swatches: [
      { label: '主色', hex: '#165DFF', primary: true, accent: '#024DE3', usage: 'blue-500' },
      { label: 'hover', hex: '#4080FF', usage: 'blue-400' },
      { label: 'active', hex: '#024DE3', usage: 'blue-600' },
      { label: '浅底', hex: '#E8F3FF', usage: 'blue-50' },
    ],
  },
];

/* ------------------------------------------------------------------ */

export function ColorSection() {
  return (
    <ComponentPage
      title="色彩 Colors"
      eng="Color"
      description={
        <>
          Arco 色板为基准的两层 token：primitive（<code>--arco-gray-1~10</code>）→
          semantic（文字 / 填充 / 边框 / 语义色），业务代码只接触 semantic 层。
        </>
      }
      whenToUse={[
        <>
          只用 semantic 层（<code>text-text-1</code> / <code>bg-fill-1</code> /{' '}
          <code>border-border-base</code> / <code>bg-success</code>…），禁止裸 hex。
        </>,
        <>
          品牌色永远走 <code>blue-*</code> 类（自动蓝⇄绿换肤），禁止写品牌 hex。列表/菜单选中浅底统一{' '}
          <code>bg-blue-500/[0.07]</code>。
        </>,
        <>
          语义色（成功/警告/危险）<strong>不参与换肤</strong>。危险浅底分两种：按钮用主色透明阶{' '}
          <code>bg-danger/10~20</code>；tag 用实色 <code>bg-danger-tint</code>（#FFECE8）。
        </>,
        <>同一语义只允许一个值（如次要文字只能 <code>text-text-2</code>）；新颜色先在色板找替代。</>,
      ]}
    >
      <ExampleGroup
        title="品牌色 Brand"
        subtitle="主色 = 500 档，跟随蓝⇄绿主题。"
      >
        <div className="space-y-8">
          <PaletteRow
            title="蓝（默认 = arcoblue）"
            swatches={[
              ...BRAND_RAMP.map((r) => ({
                label: r.step,
                hex: r.blue,
                primary: r.step === '500',
                accent: BRAND_RAMP.find((x) => x.step === '700')!.blue,
                usage: BRAND_ROLE[r.step],
              })),
              { label: 'muted', hex: '#5773B4', usage: BRAND_ROLE.muted },
            ]}
          />
          <PaletteRow
            title="绿（theme-green）"
            swatches={[
              ...BRAND_RAMP.map((r) => ({
                label: r.step,
                hex: r.green,
                primary: r.step === '500',
                accent: BRAND_RAMP.find((x) => x.step === '700')!.green,
                usage: BRAND_ROLE[r.step],
              })),
              { label: 'muted', hex: '#5C8A77', usage: BRAND_ROLE.muted },
            ]}
          />
        </div>
        <p className="mt-3 text-body-sm text-muted-foreground">
          例外（固定不换肤）：审批 tag 永远蓝、第三方 logo 原色、muted 档为低饱和品牌点缀。
        </p>
      </ExampleGroup>

      <ExampleGroup
        title="中性色 · primitive（Arco gray 1–10）"
        subtitle="中性色数值源；组件不直接用这层，走下方 semantic。"
      >
        <PaletteRow
          title="Arco gray 1–10"
          swatches={ARCO_GRAYS.map((g) => ({
            label: `gray-${g.n}`,
            hex: g.hex,
            bg: `rgb(var(--arco-gray-${g.n}))`,
            usage: ARCO_ROLE[g.n],
          }))}
        />
      </ExampleGroup>

      <ExampleGroup
        title="中性色 · semantic（组件用这层）"
        subtitle="文字 / 填充 / 边框，同一语义只有一个值。"
      >
        <CompareTable
          head={['Token', 'Tailwind 类', '取值', '用途', '实时示例']}
          rows={NEUTRAL_SEMANTIC.map((s) => [
            <code key="t" className="whitespace-nowrap">{s.token}</code>,
            <code key="c" className="whitespace-nowrap">{s.cls}</code>,
            <span key="v" className="whitespace-nowrap">{s.value}</span>,
            s.usage,
            <div key="d">{s.demo}</div>,
          ])}
        />
      </ExampleGroup>

      <ExampleGroup title="语义色 Functional（不换肤）">
        <div className="space-y-8">
          {FUNCTIONAL.map((f) => (
            <PaletteRow key={f.title} title={f.title} swatches={f.swatches} />
          ))}
        </div>
      </ExampleGroup>

      <ExampleGroup title="标签色 Tag">
        <ExampleGrid cols={1}>
          <ExampleCard title="Tag 配对一览" description="橙 / 绿 / 红三对走 token；技能紫、审批蓝为固定例外色。">
            <TagChip style={{ background: '#F5E8FF', color: '#722ED1' }}>技能（紫 · 未 token 化）</TagChip>
            <TagChip className="bg-warning-tint text-warning">助手（橙 = warning 同值）</TagChip>
            <TagChip className="bg-success-tint text-success">已完成</TagChip>
            <TagChip className="bg-danger-tint text-danger">已驳回</TagChip>
            <TagChip style={{ background: '#E8F3FF', color: '#165DFF' }}>审批中（例外：永远蓝）</TagChip>
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

    </ComponentPage>
  );
}
