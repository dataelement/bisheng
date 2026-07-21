/**
 * Typography migration ledger — DEV-ONLY.
 * The spec itself lives in the 「设计规范 → 字体」 page; this page tracks the
 * old-classname → semantic-token replacement work (docs-ui-refactor/基础-字体规范.md §8).
 */
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

export function TypographyProgress() {
  return (
    <ComponentPage
      title="字体 · 现状"
      eng="Typography Inventory"
      description={
        <>
          九档 semantic token + 系统字体栈已落地（2026-07-14）。旧 Tailwind
          默认档随组件改造逐步替换，<b>不批量改</b>。剩余工作：删死字体文件（Inter / 阿里普惠体 /
          Roboto Mono，待回归后）、清 typography.css、逐步迁移。
        </>
      }
      whenToUse={[
        <>迁移原则：随组件改造与设计师点名逐处替换，替换后逐处目检行高差异。</>,
        <>字重独立迁移：<code>font-bold / font-semibold</code>（157 处）→ <code>font-medium</code>，非本次范围。</>,
      ]}
      bodyTitle="迁移台账"
    >
      <ExampleGroup title="迁移速查" subtitle="旧写法 → 新语义类，以及两者的实际差异。">
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
