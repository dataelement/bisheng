/**
 * Modal spec page — DEV-ONLY. See docs-ui-refactor/组件-Modal弹窗.md.
 *
 * The unified modal standard is NOT finalized yet — this page documents what IS
 * decided (the C-set shell candidate) plus interim guidance, and clearly marks
 * the open questions. The full population survey and side-by-side shell
 * comparison live in progress/ModalProgress.tsx (「迁移进度 → Modal」).
 */
import { Button } from '~/components/ui/Button';
import { Input } from '~/components/ui/Input';
import {
  OGDialog,
  OGDialogTrigger,
} from '~/components/ui/OriginalDialog';
import OGDialogTemplate from '~/components/ui/OGDialogTemplate';
import { ComponentPage, ExampleGroup, ExampleGrid, ExampleCard, CompareTable } from '../components/kit';

export function ModalSection() {
  return (
    <ComponentPage
      title="Modal 弹窗"
      eng="Modal"
      description={
        <>
          承载业务内容（表单、列表、预览）的普通弹窗。<b>统一标准尚未定稿</b>
          ：已确定二次确认（C 套）壳为基准候选，B 套已对齐；遮罩 / 圆角 / 标题字重等仍在收敛中，
          定稿前以本页"已定"条目为准。现状盘点与待定项见「迁移进度 → Modal」。
        </>
      }
      whenToUse={[
        <>
          <b>已定 · 壳基准候选</b>：圆角 16（<code>rounded-2xl</code>）/ 内边距 p-5 /
          灰底毛玻璃遮罩（<code>bg-gray-500/90</code> + blur）/ 标题 <code>font-medium</code>。
        </>,
        <>
          <b>过渡期建议</b>：新增业务弹窗优先 <code>OGDialogTemplate</code>
          （壳已对齐基准候选，取消/确认按钮已统一）；不要再新增手拼 <code>AlertDialog</code> 弹窗。
        </>,
        <>纯「确认 / 取消」的二次确认不属于本页 —— 用 <code>useConfirm()</code>（见「二次确认弹窗」）。</>,
        <>窄屏下弹层贴边距 <code>calc(100% - 2rem)</code>、footer 按钮等宽平铺（见「多端适配」§③）。</>,
      ]}
    >
      <ExampleGroup
        title="基准候选壳（跟二次确认同源）"
        subtitle="以 OGDialogTemplate 实时渲染 —— 这就是当前推荐的新弹窗写法。"
      >
        <ExampleGrid cols={2}>
          <ExampleCard
            title="标准结构：标题 + 正文 + 取消/确定"
            description="OGDialogTemplate · selectVariant: primary · 圆角16 / p-5 / 灰底毛玻璃"
          >
            <OGDialog>
              <OGDialogTrigger asChild>
                <Button variant="outline">打开</Button>
              </OGDialogTrigger>
              <OGDialogTemplate
                title="弹窗标题"
                description="标题下的说明文字。"
                className="max-w-md"
                main={
                  <div className="flex flex-col gap-3">
                    <p className="text-body text-text-primary">
                      这里是弹窗正文示例。观察内边距、行距与正文和标题/按钮的间距。
                    </p>
                    <Input placeholder="示例输入框" />
                  </div>
                }
                selection={{
                  selectHandler: () => null,
                  selectVariant: 'primary',
                  selectText: '确定',
                }}
              />
            </OGDialog>
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup title="壳规格（已定部分）" subtitle="与二次确认弹窗同一套壳；下表为基准候选的确定值。">
        <CompareTable
          head={['部位', '值', '备注']}
          rows={[
            ['圆角', <code key="c">rounded-2xl（16px）</code>, '移动端是否保留直角/贴底待定'],
            ['内边距', <code key="c">p-5（20px）· 区块间 gap-4</code>, ''],
            ['遮罩', <><code>bg-gray-500/90</code> + <code>backdrop-blur-md</code></>, '灰底毛玻璃'],
            ['边框 / 阴影', <code key="c">border #ebebeb + 淡投影</code>, ''],
            ['标题', <code key="c">text-base font-medium leading-6</code>, ''],
            ['取消 / 确认按钮', '白底描边 + danger/primary 两档', '与二次确认一致'],
          ]}
        />
        <p className="mt-3 text-body-sm text-muted-foreground">
          仍待定：A 套（最大人群）的遮罩 / 圆角 / 标题字重是否并入基准、z-index 档位、footer
          按钮间距。定稿后本页升级为完整规范。
        </p>
      </ExampleGroup>
    </ComponentPage>
  );
}
