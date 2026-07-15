/**
 * Confirm dialog spec page — DEV-ONLY. See docs-ui-refactor/组件-Modal弹窗.md.
 *
 * Standard usage of the finalized confirm dialog: the app-wide useConfirm()
 * service (ConfirmContext, AlertDialog-based) with its two variants, plus the
 * finalized shell/button anatomy. Migration ledger (legacy OGDialogTemplate
 * selection populations, selectClasses inventory): progress/ConfirmProgress.tsx.
 */
import { Button } from '~/components/ui/Button';
import { useConfirm } from '~/Providers';
import { ComponentPage, ExampleGroup, ExampleGrid, ExampleCard, CompareTable } from '../components/kit';

function UseConfirmDemos() {
  const confirm = useConfirm();
  return (
    <>
      <ExampleCard
        title="危险态（variant: destructive）"
        description="红图标 + 红标题 + 暂不 / 确认删除 —— 删除等不可逆操作"
      >
        <Button
          variant="outline"
          onClick={() =>
            confirm({
              variant: 'destructive',
              description:
                '确认删除知识空间 "默认组织的知识空间" 吗？此操作不可逆，请谨慎删除！',
            })
          }
        >
          打开
        </Button>
      </ExampleCard>
      <ExampleCard
        title="普通态（variant: default）"
        description="橙色警示图标 + 主色确认 —— 可逆但需用户知情的操作"
      >
        <Button
          variant="outline"
          onClick={() =>
            confirm({
              variant: 'default',
              description: '切换频道后未保存的编辑将丢失，是否继续？',
            })
          }
        >
          打开
        </Button>
      </ExampleCard>
    </>
  );
}

export function ConfirmDialogSection() {
  return (
    <ComponentPage
      title="二次确认弹窗"
      eng="Confirm Dialog"
      description={
        <>
          删除 / 危险操作时的「确认 / 取消」小弹窗。标准实现是全局服务{' '}
          <code>useConfirm()</code>，分 destructive / default 两档，标准<b>已定稿</b>。
        </>
      }
      whenToUse={[
        <>
          危险操作（删除等）用 <code>useConfirm()</code>：<code>variant: destructive</code>
          （红）；可逆但需确认的用 <code>default</code>（橙色警示）。不要自拼确认弹窗。
        </>,
        <>确认按钮只两档：danger <code>#f53f3f</code> / primary 主色；取消按钮白底描边。</>,
        <>带表单输入的弹窗不是二次确认 —— 属于普通 Modal（见「Modal 弹窗」）。</>,
      ]}
    >
      <ExampleGroup title="两个变体" subtitle="useConfirm() 的全部档位；文案由业务传入。">
        <ExampleGrid cols={2}>
          <UseConfirmDemos />
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup title="规格 Anatomy" subtitle="定稿值 —— 也是普通 Modal 的壳基准候选来源。">
        <CompareTable
          head={['部位', '值', '备注']}
          rows={[
            [
              '弹窗容器',
              <code key="c">rounded-2xl p-5 gap-4 border #ebebeb + 淡投影</code>,
              '圆角 16 / padding 20',
            ],
            [
              '遮罩',
              <>
                <code>bg-gray-500/90</code> + <code>backdrop-blur-md</code>
              </>,
              '灰底毛玻璃',
            ],
            ['标题', <code key="c">text-base font-medium leading-6</code>, ''],
            [
              '确认按钮',
              <>
                两档：danger <code>#f53f3f</code> / primary 品牌主色（<code>selectVariant</code>{' '}
                指定）
              </>,
              'cva 档位 · 特例走 selectClasses 口子',
            ],
            [
              '取消按钮',
              <>
                白底描边 <code>hover:bg-[#f7f8fa]</code>，<code>focus-visible</code> 焦点环
              </>,
              '',
            ],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
