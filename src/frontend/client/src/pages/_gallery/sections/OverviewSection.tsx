/**
 * Spec overview — DEV-ONLY. The entry page of the 「设计规范」 mode: what this
 * design system is, the design principles behind it, and an index of every spec
 * page with its maturity. Migration status lives in the 「迁移进度」 mode.
 *
 * The 设计原则 block follows ant.design/docs/spec/values-cn's editorial layout:
 * a dashed derivation strip (原则 → 基础规范 → 组件规范) on top, then each
 * principle as a numbered heading + prose paragraph — no bordered cards.
 */
import { ComponentType } from 'react';
import { Outlined } from 'bisheng-icons';
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

/** The cross-cutting principles every individual spec derives from. */
const PRINCIPLES: { title: string; body: string }[] = [
  {
    title: 'Semantic token 优先',
    body: '字号、颜色、尺寸一律用语义类（text-body / text-text-2 / size="medium"），不写裸值、不写 hex。同一语义只允许一个值——新颜色先在色板找替代，确需新增走 token 评审。',
  },
  {
    title: '档位化，不自由定制',
    body: '组件用档位（size / color / variant）承载常见变化，页面按需选档；极特殊的一次性情况用 className 覆盖，不为它新增变体、不改源码。',
  },
  {
    title: '一套组件一条代码路径',
    body: '桌面与移动共用同一组件，适配全走 media query 与既有 hooks；不引入移动端组件库、不做第二套移动端组件。',
  },
  {
    title: '品牌跟主题，语义色恒定',
    body: '品牌色永远走 blue-* 类（已重指向 --brand-*，自动蓝⇄绿换肤），禁止硬编码品牌 hex；成功/警告/危险等语义色不参与换肤。',
  },
  {
    title: '触屏与窄屏分口径',
    body: 'hover 禁用与触达面积跟"输入方式"（pointer: coarse，跟手不跟屏）；布局重排与字号重映射跟"屏幕宽度"（768px）。两种判定别混用。',
  },
  {
    title: '状态即规范',
    body: 'hover / active / disabled / loading / focus 是组件规范的一部分，由组件内置（如 Button 的 loading 属性），业务页不自拼状态样式。',
  },
];

/** 原则 → 基础规范 → 组件规范 derivation strip, antd-values style. */
const DERIVATION: { Icon: ComponentType; title: string; caption: string }[] = [
  { Icon: Outlined.Bulb, title: '设计原则', caption: '取舍与评价的统一依据' },
  { Icon: Outlined.Book, title: '基础规范', caption: '字体 / 色彩 / 多端适配 token' },
  { Icon: Outlined.ViewGridCard, title: '组件规范', caption: '各组件的档位、用法与状态' },
];

function DerivationStrip() {
  return (
    <div className="mb-12 flex flex-col items-center gap-4 rounded-xl bg-muted/20 px-8 py-7 sm:flex-row sm:gap-0">
      {DERIVATION.map(({ Icon, title, caption }, i) => (
        <div key={title} className="contents">
          {i > 0 && (
            <div className="hidden min-w-8 flex-1 items-center px-3 sm:flex" aria-hidden>
              <span className="h-px flex-1 border-t border-dashed border-border-deep" />
              <span className="-ml-px text-text-4">
                <Outlined.Right />
              </span>
            </div>
          )}
          <div className="flex w-40 flex-col items-center text-center">
            <span className="flex size-11 items-center justify-center rounded-full bg-blue-500/[0.08] text-h3 text-blue-500 [&_svg]:size-5">
              <Icon />
            </span>
            <div className="mt-2.5 text-h4 text-text-primary">{title}</div>
            <div className="mt-0.5 text-caption text-muted-foreground">{caption}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function OverviewSection() {
  return (
    <ComponentPage
      title="设计规范"
      eng="Overview"
      description={
        <>
          BiSheng client 前台的设计规范与组件标准：基础 token（字体 / 色彩 /
          多端适配）加上逐个统一的高频组件。页面里的演示全部是<b>真实业务组件</b>
          实时渲染——这里看到什么，业务页就是什么。
        </>
      }
      whenToUse={[
        <>左侧按分组选择规范页：每页 = 使用规则（何时使用）+ 档位/token 表 + 实时演示。</>,
        <>标注「未定稿」的组件（如 Modal）标准还在收敛中，先按页内"已定/待定"说明执行。</>,
        <>关心迁移现状 / 旧写法台账的，切顶部「迁移进度」；规范使用者无需关注。</>,
      ]}
      bodyTitle={null}
    >
      <ExampleGroup
        title="设计原则"
        subtitle="原则推导出基础规范，基础规范支撑组件规范；遇到规范没覆盖的场景，回到这六条判断。"
      >
        <DerivationStrip />
        <div className="space-y-9">
          {PRINCIPLES.map((p, i) => (
            <div key={p.title} className="flex gap-5">
              <span className="w-9 shrink-0 pt-0.5 text-h2 font-medium tabular-nums leading-7 text-blue-500">
                {String(i + 1).padStart(2, '0')}
              </span>
              <div>
                <h4 className="text-h3 text-text-primary">{p.title}</h4>
                <p className="mt-1.5 max-w-2xl text-body text-text-2">{p.body}</p>
              </div>
            </div>
          ))}
        </div>
      </ExampleGroup>

      <ExampleGroup title="规范索引" subtitle="按成熟度分级：已定稿的直接照用；未定稿的以页内说明为准。">
        <CompareTable
          head={['规范页', '内容', '成熟度', '源文档（docs-ui-refactor/）']}
          rows={[
            ['字体 Typography', '系统字体栈 + 九档 semantic 字号 + 双字重', '✅ 已定稿落地', '基础-字体规范.md'],
            ['色彩 Colors', '两层 token：Arco primitive → semantic（文字/填充/边框/语义色）', '✅ v1 已定稿落地', '基础-色彩规范.md'],
            ['多端适配 Responsive', '双判定口径 + 四条核心原则 + 窄屏布局惯例', '✅ v1 已建', '基础-多端适配原则.md'],
            ['滚动条 Scrollbar', '显隐跟随系统设置，默认不自定义 + 三个减显 utility', '✅ 已定稿落地', '基础-滚动条规范.md'],
            ['Button 按钮', 'color × variant 双轴 + 三档尺寸 + 内容形态与状态', '✅ v1 已定稿落地', '组件-Button按钮.md'],
            ['Modal 弹窗', '普通弹窗壳标准', '🟨 未定稿 · C 套壳候选', '组件-Modal弹窗.md'],
            ['二次确认弹窗', 'useConfirm() 服务 + 壳与按钮两档标准', '✅ 已定稿', '组件-Modal弹窗.md'],
            ['点赞 / 点踩', 'MessageFeedbackButtons 统一控件 + 延迟提交交互', '✅ 已定稿', '—'],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
