/**
 * Typography section — showcases the semantic type scale from
 * docs-ui-refactor/基础-字体规范.md so the designer can visually verify it.
 *
 * DEV-ONLY internal tooling, never shipped (route gated by import.meta.env.DEV).
 * The classes shown here (text-caption ... text-metric) are real Tailwind
 * classes generated from theme.extend.fontSize + CSS vars in src/style.css.
 * Resize the window below 768px to see the mobile remap (same classNames).
 */
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

interface TypeStep {
  /** Tailwind className, which is also the semantic token name. */
  cls: string;
  /** Desktop size / line-height in px. */
  desktop: string;
  /** Mobile (≤768px) size / line-height in px. */
  mobile: string;
  weight: 400 | 500;
  usage: string;
}

/** Ordered small → large, matching the spec's §2 semantic table. */
const SCALE: TypeStep[] = [
  { cls: 'text-caption', desktop: '12 / 20', mobile: '12 / 20', weight: 400, usage: '时间戳、标签、水印' },
  { cls: 'text-body-sm', desktop: '13 / 21', mobile: '14 / 22', weight: 400, usage: '密集表格、侧栏次要项' },
  { cls: 'text-body', desktop: '14 / 22', mobile: '16 / 24', weight: 400, usage: '正文基准，表单、表格默认' },
  { cls: 'text-h4', desktop: '16 / 24', mobile: '16 / 24', weight: 500, usage: '强调正文、四级标题' },
  { cls: 'text-h3', desktop: '18 / 26', mobile: '17 / 25', weight: 500, usage: '卡片标题' },
  { cls: 'text-h2', desktop: '20 / 28', mobile: '18 / 26', weight: 500, usage: '区块标题' },
  { cls: 'text-h1', desktop: '24 / 32', mobile: '22 / 30', weight: 500, usage: '页面标题' },
  { cls: 'text-display', desktop: '30 / 38', mobile: '26 / 34', weight: 500, usage: '大标题、营销场景' },
  { cls: 'text-metric', desktop: '36 / 44', mobile: '30 / 38', weight: 500, usage: 'Dashboard 核心指标数字' },
];

const SAMPLE_ZH = '毕昇平台让大模型应用触手可及';
const SAMPLE_EN = 'The quick brown fox jumps over the lazy dog 0123456789';

interface FontStack {
  /** Tailwind className (also usable in plain CSS via the stack value). */
  cls: string;
  /** Design token name in the spec (§1). */
  token: string;
  usage: string;
  /** The actual comma-joined stack, for display. */
  stack: string;
  /** Live sample lines rendered with this stack. */
  samples: string[];
}

/** §1 font stacks — pure system fonts, zero webfont loading. */
const FONT_STACKS: FontStack[] = [
  {
    cls: 'font-sans',
    token: 'font-family-base',
    usage: '全局默认（已写入 body/html，无需显式加类）',
    stack:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif',
    samples: [SAMPLE_ZH, SAMPLE_EN],
  },
  {
    cls: 'font-mono',
    token: 'font-family-mono',
    usage: 'ID、代码、日志',
    stack: 'ui-monospace, "SF Mono", "Cascadia Mono", Consolas, "Liberation Mono", monospace',
    samples: ['wf_a1b2c3 · 0123456789', 'const answer = 42; // code sample'],
  },
];

export function TypographySection() {
  return (
    <ComponentPage
      title="字体 Typography"
      eng="Typography"
      description="九档 semantic 字号（自带字重）+ 两档字重。系统字体栈已全量切换；窗口缩到 ≤768px 可看移动端重映射（className 不变）。"
      whenToUse={[
        <>组件与业务代码只用 semantic 类（<code>text-body</code> / <code>text-h1</code>…），不写裸 <code>text-sm</code> 或数值。</>,
        <>字重只用 <code>font-normal</code>(400) / <code>font-medium</code>(500) 两档，禁用 600/700。</>,
        <>标题层级连续使用（h1→h2→h3），不跳级取字号。</>,
        <>数字/金额加 <code>tabular-nums</code>；ID、代码用 <code>font-mono</code>。</>,
      ]}
    >
      <ExampleGroup
        title="字体栈 Font Family"
        subtitle="纯系统字体栈，零加载成本：Mac/iOS 命中 SF + 苹方，Windows 命中 Segoe UI + 微软雅黑，Android 命中 Roboto + 思源黑体。两步法第①步已切栈，旧字体文件（Inter / 阿里普惠体 / Roboto Mono）保留待回归后删除。"
      >
        <CompareTable
          head={['Token / 类名', '实时示例 + 完整字体栈', '用途']}
          rows={FONT_STACKS.map((f) => [
            <div key="t" className="whitespace-nowrap">
              <code className="text-body-sm text-text-primary">{f.token}</code>
              <div className="mt-0.5 text-caption">
                类名 <code>{f.cls}</code>
              </div>
            </div>,
            <div key="s" className="min-w-[20rem]">
              <div className="text-text-primary">
                {f.samples.map((s) => (
                  <div key={s} className={`${f.cls} truncate text-h4 font-normal`}>
                    {s}
                  </div>
                ))}
              </div>
              <div className="mt-1.5 break-all font-mono text-caption">{f.stack}</div>
            </div>,
            f.usage,
          ])}
        />
      </ExampleGroup>

      <ExampleGroup
        title="字号阶梯 Semantic"
        subtitle="与规范 §2 Semantic 表同构，末列为该档实时渲染。移动列在窗口 ≤768px 时生效（className 不变）。"
      >
        <CompareTable
          head={['Token', '桌面 (size/line)', '移动 (size/line)', '字重', '实时示例（内容即用途）']}
          rows={SCALE.map((step) => [
            <code key="t" className="whitespace-nowrap text-body-sm text-text-primary">
              {step.cls}
            </code>,
            <span key="d" className="whitespace-nowrap tabular-nums">{step.desktop}</span>,
            <span key="m" className="whitespace-nowrap tabular-nums">{step.mobile}</span>,
            String(step.weight),
            <div key="s" className={`${step.cls} text-text-primary`}>{step.usage}</div>,
          ])}
        />
      </ExampleGroup>

      {/* Font weights — the only two allowed steps */}
      <ExampleGroup title="字重 Font Weight" subtitle="只使用 400 / 500 两档，禁用 600/700（微软雅黑缺中间字重，会合成粗体）。">
        <CompareTable
          head={['Token / 类名', '值', '实时示例（内容即用途）']}
          rows={[
            { cls: 'font-normal', token: 'font-weight-regular', weight: 400, usage: '正文、说明' },
            { cls: 'font-medium', token: 'font-weight-medium', weight: 500, usage: '标题、强调、按钮' },
          ].map((w) => [
            <div key="t" className="whitespace-nowrap">
              <code className="text-body-sm text-text-primary">{w.token}</code>
              <div className="mt-0.5 text-caption">
                类名 <code>{w.cls}</code>
              </div>
            </div>,
            String(w.weight),
            /* text-h3 carries fontWeight 500; inline style deterministically overrides it */
            <div key="s" className="text-h3 text-text-primary" style={{ fontWeight: w.weight }}>
              {w.usage}
            </div>,
          ])}
        />
      </ExampleGroup>

      {/* Quick reference for migration */}
      <ExampleGroup title="迁移速查" subtitle="随组件改造逐步替换，本次不批量改">
      <CompareTable
        head={['旧写法（Tailwind 默认档）', '新语义类', '差异']}
        rows={[
          ['text-xs (12/16)', 'text-caption (12/20)', '行高 16→20'],
          ['text-sm (14/20)', 'text-body (14/22)', '行高 20→22，规范化 lh = size + 8'],
          ['text-base (16/24)', 'text-h4 (16/24, 500) 或正文场景 text-body', '按语义选择'],
          ['text-lg (18/28)', 'text-h3 (18/26, 500)', '行高 28→26，自带 500 字重'],
          ['text-xl (20/28)', 'text-h2 (20/28, 500)', '自带 500 字重'],
          ['text-2xl (24/32)', 'text-h1 (24/32, 500)', '自带 500 字重'],
          ['font-bold / font-semibold (157 处)', 'font-medium', '独立迁移，非本次范围'],
        ]}
      />
      </ExampleGroup>
    </ComponentPage>
  );
}
