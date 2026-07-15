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

/** Labeled swatch for the functional-color state rows. */
function StateSwatch({
  className,
  style,
  label,
  sub,
}: {
  className?: string;
  style?: CSSProperties;
  label: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className={cn('inline-block h-9 w-16 rounded-md border border-black/10', className)} style={style} />
      <span className="text-caption text-text-primary">{label}</span>
      {sub && <code className="text-caption text-muted-foreground">{sub}</code>}
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
 * Spec data
 * ------------------------------------------------------------------ */

/** §1.1 brand ramp — blue/green documentation values. */
const BRAND_RAMP = [
  { step: '50', blue: '#E8F3FF', green: '#E4F1EC', usage: '浅底一档：选中背景；按钮 filled 底 / outlined·text hover' },
  { step: '100', blue: '#BEDAFF', green: '#CCE4DA', usage: '浅底二档：filled hover / outlined·text 触屏 active' },
  { step: '200', blue: '#94BFFF', green: '#A3D2C0', usage: '浅底三档：filled 触屏 active' },
  { step: '300', blue: '#6AA1FF', green: '#6FBAA0', usage: '' },
  { step: '400', blue: '#4080FF', green: '#3D9B78', usage: 'hover（比主色亮一档）' },
  { step: '500', blue: '#165DFF', green: '#169C47', usage: '主色（= --brand-main）' },
  { step: '600', blue: '#024DE3', green: '#136345', usage: 'active / 按下（深一档）' },
  { step: '700', blue: '#0239AB', green: '#0F4D36', usage: '' },
  { step: '800', blue: '#042B80', green: '#0A3826', usage: '' },
  { step: '900', blue: '#051D52', green: '#062619', usage: '' },
];

/** §2.1 primitive Arco gray ramp — rendered live from --arco-gray-N. */
const ARCO_GRAYS = [
  { n: 1, hex: '#F7F8FA', note: 'hover 底 → fill-1' },
  { n: 2, hex: '#F2F3F5', note: 'filled 控件底 → fill-2' },
  { n: 3, hex: '#E5E6EB', note: '常规边框 → border-base / fill-3' },
  { n: 4, hex: '#C9CDD4', note: '禁用/占位 → text-4 / fill-4 / border-deep' },
  { n: 5, hex: '#A9AEB8', note: '' },
  { n: 6, hex: '#86909C', note: '辅助文字 → text-3（全站最高频 hex ×263）' },
  { n: 7, hex: '#6B7785', note: '' },
  { n: 8, hex: '#4E5969', note: '次要文字 → text-2' },
  { n: 9, hex: '#272E3B', note: '' },
  { n: 10, hex: '#1D2129', note: '主文字 → text-1' },
];

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

/* ------------------------------------------------------------------ */

export function ColorSection() {
  return (
    <ComponentPage
      title="色彩 Colors"
      eng="Color"
      description={
        <>
          Arco 色板为基准的两层 token：primitive（<code>--arco-gray-1~10</code>）→ semantic（
          <code>--text-1~4</code> / <code>--fill-1~4</code> / <code>--border-base|-deep</code> /{' '}
          <code>--success|warning|danger-*</code>）。命名注：规范里的语义名 <code>border</code> 与
          shadcn 的 <code>--border</code>（HSL）及 Tailwind 边框类冲突，落地为{' '}
          <code>border-base</code>（类 <code>border-border-base</code>，与现有{' '}
          <code>border-border-light</code> 同构）。
        </>
      }
      whenToUse={[
        <>
          组件与业务代码只用 semantic 层（<code>text-text-1</code> / <code>bg-fill-1</code> /{' '}
          <code>border-border-base</code> / <code>bg-success</code>…），不用{' '}
          <code>--arco-gray-*</code> primitive（Tailwind 故意未接线），禁止裸 hex。
        </>,
        <>
          品牌色永远走 <code>blue-*</code> 类（已重指向 <code>--brand-*</code>，自动蓝⇄绿换肤）或{' '}
          <code>rgb(var(--brand-NNN))</code>；禁止写品牌 hex。列表/菜单选中浅底统一{' '}
          <code>bg-blue-500/[0.07]</code>；按钮浅底走 50/100/200 实档。
        </>,
        <>
          语义色（成功/警告/危险）<strong>不参与换肤</strong>。危险浅底分两种：按钮用主色透明阶{' '}
          <code>bg-danger/10~20</code>；tag 用实色 <code>bg-danger-tint</code>（#FFECE8）。
        </>,
        <>同一语义只允许一个值（如次要文字只能 <code>text-text-2</code>）；新颜色先在色板找替代，确需新增走 token 评审进 primitive 层。</>,
      ]}
    >
      <ExampleGroup
        title="品牌色 Brand（跟随蓝⇄绿主题）"
        subtitle="蓝/绿两列为规范文档值（固定展示）。业务里写 blue-* 类即自动跟随当前主题。muted 档与固定色例外见表下说明。"
      >
        <CompareTable
          head={['档', '蓝（默认 = arcoblue）', '绿（theme-green）', '语义']}
          rows={[
            ...BRAND_RAMP.map((r) => [
              <code key="s" className={r.step === '500' ? 'font-medium text-text-primary' : ''}>{r.step}</code>,
              <ColorCell key="b" hex={r.blue} />,
              <ColorCell key="g" hex={r.green} />,
              r.usage,
            ]),
            [
              <code key="s">muted</code>,
              <ColorCell key="b" hex="#5773B4" />,
              <ColorCell key="g" hex="#5C8A77" />,
              '低饱和品牌点缀（如置顶 pin）· --brand-muted',
            ],
          ]}
        />
        <p className="mt-3 text-body-sm text-muted-foreground">
          固定色例外（永远不换肤，别误改）：审批中 tag 永远蓝 <code>#E8F3FF/#165DFF</code>
          （ApprovalCenterDialog）；应用中心置顶 pin 用 <code>--brand-muted</code>；第三方 logo
          原色保留。选中浅底示例：
          <span className="ml-2 inline-flex items-center rounded-md bg-blue-500/[0.07] px-2 py-0.5 text-blue-500">
            bg-blue-500/[0.07]
          </span>
        </p>
      </ExampleGroup>

      <ExampleGroup
        title="中性色 Neutral · primitive（Arco gray 1–10）"
        subtitle="唯一中性色板，数值源。色块用 rgb(var(--arco-gray-N)) 实时渲染（验证 token 已生效）；组件不允许直接用这层。"
      >
        <CompareTable
          head={['Primitive Token', '色值', '去向（semantic）/ 现状']}
          rows={ARCO_GRAYS.map((g) => [
            <code key="t" className="whitespace-nowrap">--arco-gray-{g.n}</code>,
            <ColorCell key="c" style={{ background: `rgb(var(--arco-gray-${g.n}))` }} label={g.hex} />,
            g.note,
          ])}
        />
      </ExampleGroup>

      <ExampleGroup
        title="中性色 Neutral · semantic（组件用这层）"
        subtitle="text-1~4 / fill-1~4 / border-base / border-deep，全部引用 primitive。末列为 Tailwind 类实时渲染。"
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

      <ExampleGroup
        title="语义色 Functional（不换肤，全主题恒定）"
        subtitle="成功/警告/危险三态 + 浅底 tint；链接/信息 Info = 品牌色（跟主题）。色块全部用新 token 类实时渲染。"
      >
        <ExampleGrid cols={2}>
          <ExampleCard title="成功 Success" description="Arco green：#00B42A / hover #23C343 / active #009A29 / tint #E8FFEA">
            <StateSwatch className="bg-success" label="主色" sub="bg-success" />
            <StateSwatch className="bg-success-hover" label="hover" sub="-hover" />
            <StateSwatch className="bg-success-active" label="active" sub="-active" />
            <StateSwatch className="bg-success-tint" label="tint" sub="-tint" />
          </ExampleCard>
          <ExampleCard title="警告 Warning" description="Arco orange：#FF7D00 / hover #FF9A2E / active #D25F00 / tint #FFF7E8">
            <StateSwatch className="bg-warning" label="主色" sub="bg-warning" />
            <StateSwatch className="bg-warning-hover" label="hover" sub="-hover" />
            <StateSwatch className="bg-warning-active" label="active" sub="-active" />
            <StateSwatch className="bg-warning-tint" label="tint" sub="-tint" />
          </ExampleCard>
          <ExampleCard title="危险 Danger" description="#F53F3F / hover #D6373A / active #D02F33（与 --btn-danger* 同值）；tint #FFECE8 仅 tag 用">
            <StateSwatch className="bg-danger" label="主色" sub="bg-danger" />
            <StateSwatch className="bg-danger-hover" label="hover" sub="-hover" />
            <StateSwatch className="bg-danger-active" label="active" sub="-active" />
            <StateSwatch className="bg-danger-tint" label="tint" sub="-tint" />
          </ExampleCard>
          <ExampleCard
            title="危险浅底的两种场景"
            description="按钮里的浅红底＝主色叠透明（hover 10% / 触屏按下 15% / filled 递进到 20%）；tag 浅红底＝实色 danger-tint。"
          >
            <StateSwatch className="bg-danger/10" label="按钮 10%" sub="bg-danger/10" />
            <StateSwatch className="bg-danger/[0.15]" label="15%" sub="/[0.15]" />
            <StateSwatch className="bg-danger/20" label="20%" sub="/20" />
            <TagChip className="bg-danger-tint text-danger">已驳回（tag 实色）</TagChip>
          </ExampleCard>
          <ExampleCard
            title="链接 / 信息 Info = 品牌色"
            description="本项目 info 即品牌（与 antd 单独 info 蓝不同），跟随蓝⇄绿主题：文字 blue-500 → hover blue-400 → 触屏 active blue-600，浅底 blue-50。"
          >
            <StateSwatch className="bg-blue-500" label="主色" sub="blue-500" />
            <StateSwatch className="bg-blue-400" label="hover" sub="blue-400" />
            <StateSwatch className="bg-blue-600" label="active" sub="blue-600" />
            <StateSwatch className="bg-blue-50" label="浅底" sub="blue-50" />
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup
        title="扩展 / 标签色 Tag（成对使用：浅底 + 深字）"
        subtitle="Arco 1 号浅底 + 6 号主色字。技能紫与固定蓝未 token 化（紫待后续评审；固定蓝是「永远蓝」例外），此处为文档展示值。"
      >
        <ExampleGrid cols={1}>
          <ExampleCard title="Tag 配对一览" description="橙/绿/红三对已走 token 类；紫与固定蓝为展示用文档值。">
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
