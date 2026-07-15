/**
 * Multi-device adaptation principles — DEV-ONLY.
 * Mirrors docs-ui-refactor/基础-多端适配原则.md: cross-component responsive rules
 * (touch vs width criteria, hover/active, hit-area, one code path). Principles-only
 * page — no live component demos, so it's table/text driven.
 */
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

export function ResponsiveSection() {
  return (
    <ComponentPage
      title="多端适配"
      eng="Responsive"
      description={
        <>
          跨组件通用适配原则，适用响应式 Web（桌面 + 移动端浏览器/H5），<b>无原生 App</b>。
          组件专属细则见各组件文档的「移动端适配」节。
        </>
      }
      whenToUse={[
        <>
          <b>两种判定口径别混用</b>：<code>输入方式</code>（是不是触屏）管 hover 禁用与触达面积——跟手不跟屏；
          <code>屏幕宽度</code>（窄不窄）管布局重排与字号重映射。
        </>,
        <>一套组件一条代码路径：不引入 antd-mobile、不做第二套移动端组件，适配全走 CSS 规则与既有 hooks。</>,
        <>控件字号不随正文抬升（移动端 14→16 只作用于阅读文本）；唯一例外：输入框 ≥16px。</>,
      ]}
      bodyTitle={null}
    >
      <ExampleGroup title="① 两种判定口径（先分清，别混用）">
        <CompareTable
          head={['口径', '写法', '判定什么', '用于']}
          rows={[
            [
              '输入方式',
              <code key="a">@media (hover: none) and (pointer: coarse)</code>,
              '是不是触屏（无悬停、手指粗）',
              'hover 禁用、触达面积 — 跟手不跟屏（触屏笔记本/平板横屏也生效）',
            ],
            [
              '屏幕宽度',
              <code key="b">@media (max-width: 768px)</code>,
              '屏幕窄不窄',
              '布局重排（等宽平铺、block、贴底弹层）、字号重映射',
            ],
          ]}
        />
      </ExampleGroup>

      <ExampleGroup title="② 四条核心原则">
        <CompareTable
          head={['原则', '怎么做', '依据']}
          rows={[
            [
              '触屏禁 hover，用 active 补偿',
              '触屏下禁用 hover 态（防 sticky hover），按下反馈交给 active；active 深档只在触屏生效，可 hover 设备按下直接显示 hover 档。已全局落地 tailwind future.hoverOnlyWhenSupported，普通 hover: 类即可。',
              'antd-mobile 源码通篇仅 :active；移动组件库共识',
            ],
            [
              '触达面积 ≥ 44×44px',
              '视觉尺寸不变，用透明伪元素/padding 撑热区；<28px 小控件高频触屏场景直接升档，不硬撑。',
              'WCAG 2.2 §2.5.5(AAA)、iOS HIG 44pt、Material 48dp',
            ],
            [
              '控件字号不随正文抬升',
              '按钮/标签/菜单项保持桌面值（≥14）；唯一例外输入框 ≥16px（iOS 自动放大问题）。',
              '字体规范 §2 / §5.1',
            ],
            [
              '一套组件一条代码路径',
              '适配全走 media query / sm: 前缀 + useMediaQuery / usePrefersMobileLayout，在同一组件内完成。',
              '与字体规范"media 重映射、组件不变"同思路',
            ],
          ]}
        />
      </ExampleGroup>

      <ExampleGroup title="③ 窄屏布局惯例（已有先例，新组件沿用）">
        <CompareTable
          head={['场景', '窄屏', '桌面']}
          rows={[
            ['弹层 footer 按钮', <>等宽平铺 <code key="a">flex-1</code></>, <>右对齐自适应宽 <code key="b">sm:flex-none</code></>],
            ['主操作', '占满整行 block', '自适应宽'],
            ['弹层容器', <>贴边距 <code key="c">calc(100% - 2rem)</code> 或贴底滑入</>, '居中固定宽'],
          ]}
        />
      </ExampleGroup>

      <ExampleGroup title="④ 组件适配细则索引" subtitle="通用原则在此；组件专属细则在各组件文档，建后登记于此。">
        <CompareTable
          head={['组件', '细则位置']}
          rows={[
            ['Button', 'docs-ui-refactor/组件-Button按钮.md §5.5'],
            ['Modal / 字体 / Select …', '各组件文档补"移动端适配"节，建后登记'],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
