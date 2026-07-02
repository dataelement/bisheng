/**
 * Modal / Dialog gallery — DEV-ONLY. See docs-ui-refactor/组件-Modal弹窗.md.
 *
 * Renders BiSheng's two parallel dialog families side by side so the difference
 * (overlay darkness / blur / z-index) is visible by opening them.
 */
import { Button } from '~/components/ui/Button';
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '~/components/ui/Dialog';
import {
  OGDialog,
  OGDialogTrigger,
  OGDialogContent,
  OGDialogHeader,
  OGDialogTitle,
  OGDialogDescription,
} from '~/components/ui/OriginalDialog';
import DialogTemplate from '~/components/ui/DialogTemplate';
import OGDialogTemplate from '~/components/ui/OGDialogTemplate';
import { Section, Demo, DemoGrid, CompareTable } from '../components/kit';

const sampleBody = (
  <p className="text-sm text-text-primary">
    这里是弹窗正文示例。放一段说明文字、表单或列表，用来观察内边距、行距与滚动表现。
  </p>
);

export function ModalSection() {
  return (
    <Section
      id="modal"
      title="Modal 弹窗"
      subtitle={
        <>
          现状有 <b>两套并行体系</b>：A 套 <code>Dialog</code>（毛玻璃遮罩 z-100）与 B 套{' '}
          <code>OriginalDialog / OG</code>（纯深色遮罩 z-50）。逐个打开对比背景暗度、模糊、层级。
        </>
      }
    >
      {/* Difference table */}
      <div className="mb-6">
        <CompareTable
          head={['维度', 'A 套 Dialog', 'B 套 OriginalDialog / OG']}
          rows={[
            ['遮罩颜色', 'bg-black/40（浅）', 'bg-black/80（深）'],
            ['毛玻璃模糊', '有 backdrop-blur-md', '无'],
            ['层级 z-index', 'z-[100]', 'z-50'],
            ['便捷模板', 'DialogTemplate（~4 处）', 'OGDialogTemplate（~25 处 · 用得最多）'],
          ]}
        />
      </div>

      <DemoGrid cols={4}>
        {/* A-set raw primitives */}
        <Demo label="A 套 · Dialog 原语" note="ui/Dialog.tsx · 毛玻璃遮罩">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">打开</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Dialog 原语</DialogTitle>
                <DialogDescription>手动拼 Header / Footer 的底层版本。</DialogDescription>
              </DialogHeader>
              {sampleBody}
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">取消</Button>
                </DialogClose>
                <Button>确定</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </Demo>

        {/* A-set template */}
        <Demo label="A 套 · DialogTemplate" note="ui/DialogTemplate.tsx">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">打开</Button>
            </DialogTrigger>
            <DialogTemplate
              title="DialogTemplate"
              description="传 title / main / buttons 的便捷版。"
              main={sampleBody}
              buttons={<Button>确定</Button>}
            />
          </Dialog>
        </Demo>

        {/* B-set raw primitives */}
        <Demo label="B 套 · OG 原语" note="ui/OriginalDialog.tsx · 纯深色遮罩">
          <OGDialog>
            <OGDialogTrigger asChild>
              <Button variant="outline">打开</Button>
            </OGDialogTrigger>
            <OGDialogContent className="w-11/12 max-w-lg bg-background text-foreground">
              <OGDialogHeader>
                <OGDialogTitle>OG 原语</OGDialogTitle>
                <OGDialogDescription>OriginalDialog 底层版本。</OGDialogDescription>
              </OGDialogHeader>
              <div className="py-2">{sampleBody}</div>
            </OGDialogContent>
          </OGDialog>
        </Demo>

        {/* B-set template — the most used one */}
        <Demo label="B 套 · OGDialogTemplate" note="用得最多 · 基准候选">
          <OGDialog>
            <OGDialogTrigger asChild>
              <Button>打开</Button>
            </OGDialogTrigger>
            <OGDialogTemplate
              title="OGDialogTemplate"
              description="全站用得最多的便捷模板，收敛基准候选。"
              className="max-w-lg"
              main={sampleBody}
              buttons={<Button>确定</Button>}
            />
          </OGDialog>
        </Demo>
      </DemoGrid>
    </Section>
  );
}
