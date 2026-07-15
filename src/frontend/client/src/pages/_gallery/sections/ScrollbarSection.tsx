/**
 * Scrollbar spec page — DEV-ONLY. See docs-ui-refactor/基础-滚动条规范.md.
 *
 * Core rule: scrollbar visibility follows the OS setting. The old global forced
 * ::-webkit-scrollbar rule was removed (2026-07-15); native scrollbars are now
 * the default everywhere. The demos below scroll for real so the behavior can be
 * checked against the current system preference.
 */
import { ComponentPage, ExampleGroup, ExampleGrid, ExampleCard, CompareTable } from '../components/kit';

/** Tall filler so every demo box actually overflows and can be scrolled. */
function ScrollFiller({ lines = 14 }: { lines?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <p key={i} className="text-body-sm text-text-2">
          第 {i + 1} 行示例内容 —— 滚动这个区域，观察滚动条的出现方式。
        </p>
      ))}
    </div>
  );
}

export function ScrollbarSection() {
  return (
    <ComponentPage
      title="滚动条 Scrollbar"
      eng="Scrollbar"
      description={
        <>
          全站滚动条显隐<b>跟随系统设置</b>：系统设为"始终显示"就常驻，设为"滚动时显示"就自动隐藏。
          做法是<b>默认什么都不写</b>——原生滚动条天然跟随系统；一旦写了{' '}
          <code>::-webkit-scrollbar</code>，系统的自动隐藏（overlay）行为即失效，滚动条被强制常驻。
          旧的全局强制细滚动条样式已于 2026-07-15 移除。
        </>
      }
      whenToUse={[
        <>
          <b>默认不自定义</b>：任何滚动区域都不要写 <code>::-webkit-scrollbar</code> /{' '}
          <code>scrollbar-width</code>，让浏览器原生滚动条跟随系统设置。
        </>,
        <>
          <b>禁止强制常驻</b>：不允许出现"系统设了滚动时显示、页面里却常驻一根滚动条"的情况；
          新增自定义滚动条样式需先过规范评审。
        </>,
        <>
          例外只允许"更少可见"：完全隐藏 / 滚动时才显示 / hover 才显示三个既有
          utility（见下表），不允许反向做"强制显示"。
        </>,
        <>
          旧逃生口 <code>.scrollbar-os</code>（约 33 处）现已是默认行为、成为空类：新代码不要再加，
          存量随改动顺手删除。
        </>,
      ]}
    >
      <ExampleGroup
        title="默认行为（原生，跟随系统）"
        subtitle="滚动下面的区域：macOS 设为「滚动时显示」时平时应看不到滚动条；设为「始终」时应常驻。"
      >
        <ExampleGrid cols={2}>
          <ExampleCard title="纵向滚动" description="无任何滚动条样式 —— 出现方式完全由系统决定">
            <div className="h-40 w-full overflow-y-auto rounded-lg border border-border-base p-3">
              <ScrollFiller />
            </div>
          </ExampleCard>
          <ExampleCard title="横向滚动" description="横向同理（表格、代码块的 overflow-x 容器）">
            <div className="w-full overflow-x-auto rounded-lg border border-border-base p-3">
              <p className="whitespace-nowrap text-body-sm text-text-2">
                这一行内容特别长，专门用来撑出横向滚动 —— 观察横向滚动条是否也跟随系统设置显隐。这一行内容特别长，专门用来撑出横向滚动。
              </p>
            </div>
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup
        title="许可的例外（只许更少可见）"
        subtitle="三个既有 utility，均为「减少可见性」方向；场景之外不要用，也不要新造。"
      >
        <CompareTable
          head={['类名', '行为', '典型场景', '备注']}
          rows={[
            [
              <code key="c">no-scrollbar</code>,
              '完全隐藏滚动条',
              '横向 tab 条、胶囊滚动列表',
              '内容仍可滚动，只是不画条',
            ],
            [
              <code key="c">scroll-on-scroll</code>,
              '滚动进行时才显示',
              '通知弹窗列表',
              <>
                需配合 JS 切 <code>data-scrolling</code>；Firefox 走 <code>scrollbar-color</code>
              </>,
            ],
            [
              <code key="c">scroll-no-hover</code>,
              'hover 容器时才显示',
              '侧栏、面板类长列表',
              '离开即隐藏',
            ],
          ]}
        />
        <ExampleGrid cols={2}>
          <ExampleCard title="no-scrollbar" description="能滚，但永远不画滚动条">
            <div className="no-scrollbar h-32 w-full overflow-y-auto rounded-lg border border-border-base p-3">
              <ScrollFiller lines={10} />
            </div>
          </ExampleCard>
          <ExampleCard title="scroll-no-hover" description="鼠标悬停在区域上时才出现滚动条">
            <div className="scroll-no-hover h-32 w-full overflow-y-auto rounded-lg border border-border-base p-3">
              <ScrollFiller lines={10} />
            </div>
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup
        title="遗留例外（待定夺）"
        subtitle="唯一一处仍强制自定义滚动条的地方，登记在案，由设计师决定去留。"
      >
        <CompareTable
          head={['位置', '样式', '现状']}
          rows={[
            [
              '灵思 artifact 深色预览面板（mobile.css 里按 radix tabpanel 选择器定制）',
              '深色 12px 常驻滚动条 + 深色底',
              '深色语境下原生浅色条突兀，暂保留；是否改 scroll-no-hover 待定',
            ],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
