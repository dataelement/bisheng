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
      title="Button 按钮 · 现状"
      eng="Button Inventory"
      description={
        <>
          2026-07-20 全仓重扫。<b>真正的大头不是 Button 组件，而是野生原生按钮</b>：
          <code>&lt;Button&gt;</code> 264 处，而手写 <code>&lt;button&gt;</code> 有 485 处 ——
          后者比前者还多，且完全不受设计系统约束。
        </>
      }
      whenToUse={[
        <>
          新双轴 API（<code>color</code> 属性）业务里<b>仅 1 处</b>使用 ——
          旧入参虽已自动映射为新双轴，但业务代码基本没迁。
        </>,
        <>
          缺省高度 <code>h-9</code>(36px) 已归入 medium(32px)，全站矮 4px，迁移各批带目检回归。
        </>,
      ]}
      bodyTitle="现状盘点"
    >
      <ExampleGroup
        title="① 按钮总盘"
        subtitle="全站到底有多少种“按钮”——组件化的只是其中一部分。"
      >
        <CompareTable
          head={['来源', '判定方式', '出现次数', '涉及文件', '受设计系统约束？']}
          rows={[
            [
              <b key="a">原生 &lt;button&gt;</b>,
              <code key="a2">&lt;button</code>,
              <b key="a3">485</b>,
              <b key="a4">222</b>,
              '❌ 完全不受约束，样式各写各的',
            ],
            [
              'Button 组件',
              <code key="b">&lt;Button&gt;</code>,
              '264',
              '136',
              '✅ 走 cva 档位（但 96% 仍用旧 API 入参）',
            ],
            [
              '全局 CSS 类',
              <code key="c">btn / btn-primary / btn-neutral / btn-secondary</code>,
              '—',
              '约 10',
              '❌ LibreChat 遗留全局类：ToolItem、EditMessage、EditTextPart、HeaderNewChat、PluginStoreItem…',
            ],
          ]}
        />
        <p className="mt-3 text-body-sm text-muted-foreground">
          按钮统一的真实工作量在第一行 —— 485 处原生 <code>&lt;button&gt;</code>
          里，哪些该收进 Button 组件、哪些本就该是无样式的可点区域（icon/关闭/列表项），需要逐类甄别。
        </p>
      </ExampleGroup>

      <ExampleGroup
        title="② 旧 API 兼容映射"
        subtitle="旧入参自动映射为新双轴（已标 deprecated）；右列全部用旧 API 渲染，外观应与新双轴一致。"
      >
        <CompareTable
          head={['旧写法（用量）', '映射为', '旧 API 实渲染']}
          rows={[
            [
              <code key="o">缺省 + 显式 default（98 + 7 = 105 处）</code>,
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
              <code key="o">variant=&quot;outline&quot;（77 处）</code>,
              <code key="n">default outlined</code>,
              <Button key="b" variant="outline">
                按钮
              </Button>,
            ],
            [
              <code key="o">variant=&quot;secondary&quot;（17 处）</code>,
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
              <code key="o">variant=&quot;link&quot; / secondaryBrand（0 处）</code>,
              <code key="n">primary link</code>,
              <Button key="b" variant="link">
                按钮
              </Button>,
            ],
            [
              <code key="o">size=&quot;sm&quot;（48 处，旧 h-9）</code>,
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
              <code key="o">size=&quot;icon&quot;（17 处）</code>,
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
