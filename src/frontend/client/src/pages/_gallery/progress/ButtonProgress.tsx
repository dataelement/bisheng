/**
 * Button migration ledger — DEV-ONLY.
 * The dual-axis spec lives in the 「设计规范 → Button」 page; this page keeps the
 * legacy-API mapping table (docs-ui-refactor/组件-Button按钮.md §6.3) — every button
 * below renders THROUGH the old API to verify the automatic mapping.
 */
import { Outlined } from 'bisheng-icons';
import { Button } from '~/components/ui/Button';
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

export function ButtonProgress() {
  return (
    <ComponentPage
      title="Button · 迁移"
      eng="Button Progress"
      description={
        <>
          基准组件已重构落地（2026-07-14）：旧入参自动映射为新双轴（已标
          deprecated），业务零改动先跑起来，逐批迁移后删除映射层。剩余工作：设计师验收推导值 →
          逐批迁移业务页 → 清退 <code>btn</code> 系全局类与 Generations/Button。
        </>
      }
      whenToUse={[
        <>
          缺省高度 <code>h-9</code>(36px) 已归入 medium(32px)，<b>全站矮 4px</b>
          ，迁移各批带目检回归（§6.6）。
        </>,
        <>下表右列全部用旧 API 渲染 —— 外观应与新双轴一致，即映射验收。</>,
      ]}
      bodyTitle="迁移台账"
    >
      <ExampleGroup title="旧 API 兼容映射（迁移台账，§6.3）">
        <CompareTable
          head={['旧写法（用量）', '映射为', '旧 API 实渲染']}
          rows={[
            [
              <code key="o">缺省 / variant=&quot;default&quot;（116 处）</code>,
              <code key="n">primary solid</code>,
              <Button key="b" variant="default">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;submit&quot;（11 处）</code>,
              <code key="n">primary solid（原写死 ChatGPT 绿，随迁移废除）</code>,
              <Button key="b" variant="submit">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;outline&quot;（78 处）</code>,
              <code key="n">default outlined</code>,
              <Button key="b" variant="outline">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;secondary&quot;（17 处，原 18：知识空间侧栏“创建知识空间”已迁 primary filled）</code>,
              <code key="n">default filled</code>,
              <Button key="b" variant="secondary">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;secondaryBrand&quot;（0 处）</code>,
              <code key="n">primary filled</code>,
              <Button key="b" variant="secondaryBrand">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;ghost&quot;（40 处）</code>,
              <code key="n">default text</code>,
              <Button key="b" variant="ghost">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;destructive&quot;（6 处）</code>,
              <code key="n">danger solid</code>,
              <Button key="b" variant="destructive">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;link&quot;（0 处）</code>,
              <code key="n">primary link</code>,
              <Button key="b" variant="link">
                按钮
              </Button>,
            ],
            [
              <code key="o">size 缺省 / &quot;sm&quot;（249 处，旧 h-9）</code>,
              <code key="n">medium（32px）</code>,
              <Button key="b" variant="outline" size="sm">
                按钮
              </Button>,
            ],
            [
              <code key="o">size=&quot;lg&quot;（2 处）</code>,
              <code key="n">large（40px）</code>,
              <Button key="b" size="lg">
                按钮
              </Button>,
            ],
            [
              <code key="o">size=&quot;icon&quot;（18 处）</code>,
              <code key="n">medium + iconOnly</code>,
              <Button key="b" variant="outline" size="icon" aria-label="搜索">
                <Outlined.Search />
              </Button>,
            ],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
