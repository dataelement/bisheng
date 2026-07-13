/**
 * Modal / Dialog gallery — DEV-ONLY. See docs-ui-refactor/组件-Modal弹窗.md.
 *
 * Fresh survey (2026-07-09): FIVE coexisting modal populations. The same demo
 * content (title + description + input + cancel/confirm footer) is mounted into
 * each shell so the shell differences (overlay / radius / padding / title /
 * buttons) are the only variable when opening them side by side.
 */
import { Button } from '~/components/ui/Button';
import { Input } from '~/components/ui/Input';
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
import {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
} from '~/components/ui/AlertDialog';
import DialogTemplate from '~/components/ui/DialogTemplate';
import OGDialogTemplate from '~/components/ui/OGDialogTemplate';
import { useConfirm } from '~/Providers';
import { Section, Demo, DemoGrid, CompareTable } from '../components/kit';

/** Identical body for every shell so only the shell itself differs. */
const demoBody = (
  <div className="flex flex-col gap-3">
    <p className="text-sm text-text-primary">
      这里是弹窗正文示例。观察内边距、行距与正文和标题/按钮的间距。
    </p>
    <Input placeholder="示例输入框" />
  </div>
);

/** Small reference demo of the finalized confirm dialog, for shell comparison. */
function ConfirmReferenceDemo() {
  const confirm = useConfirm();
  return (
    <Button
      variant="outline"
      onClick={() =>
        confirm({
          variant: 'destructive',
          title: '确认删除',
          description: '弹窗壳视觉参照：圆角16 / p-5 / 灰底毛玻璃遮罩。',
          confirmText: '确认删除',
        })
      }
    >
      打开
    </Button>
  );
}

export function ModalSection() {
  return (
    <Section
      id="modal"
      title="Modal 弹窗"
      subtitle={
        <>
          2026-07-09 重新盘点：全站普通弹窗共 <b>5 个并行体系、约 64 个业务文件</b>
          。二次确认期已把 B 套壳对齐 C 套视觉，但 A 套（原语直接拼 22 处 + 模板 3
          处）与手拼 AlertDialog（7 处）仍是另外两种壳。逐个打开对比，定统一标准。
        </>
      }
    >
      {/* ① Population overview */}
      <h3 className="mb-3 mt-2 text-base font-semibold text-text-primary">
        ① 用量盘子（当前精确扫描，排除 ui/ 与画廊）
      </h3>
      <div className="mb-8">
        <CompareTable
          head={['体系', '实现', '业务文件数', '用在哪 / 备注']}
          rows={[
            [
              'A 套 · 原语直接拼',
              'Dialog + DialogContent 手拼',
              <b key="a1">22（最大人群）</b>,
              '新页面为主：知识库 8、订阅 2、审批/通知/账号/分享/appChat…（含 MainLayout 全局弹窗）',
            ],
            [
              'A 套 · 模板',
              'DialogTemplate',
              '3',
              'EditPresetDialog、PresetItems、ContextButton（后者在 SidePanel 死树）',
            ],
            [
              'B 套 · 模板',
              'OGDialogTemplate',
              '16（原 25，确认迁移后）',
              '书签/导出/SetKey/归档/Agent 面板…（其中 SidePanel 死树约 6 处）；壳已对齐 C 套',
            ],
            [
              'B 套 · 原语直接拼',
              'OGDialog + OGDialogContent 手拼',
              '16',
              '设置（账号/数据）、Prompts、文件预览、ShareAgent…；壳同上（已对齐 C 套）',
            ],
            [
              '手拼 AlertDialog',
              'AlertDialogContent + 自拼头尾',
              '7',
              '频道成员 2、爬取系 4、灵思 TaskModeInput（部分带确认性质，本期一并处理）',
            ],
            [
              'C 套 · useConfirm（参照）',
              'ConfirmContext（AlertDialog 底层）',
              '26（已收敛 ✅）',
              '二次确认已定稿的视觉基准：圆角16 / p-5 / 灰底毛玻璃 —— Modal 壳的天然候选',
            ],
          ]}
        />
      </div>

      {/* ② Shell anatomy */}
      <h3 className="mb-3 text-base font-semibold text-text-primary">
        ② 壳样式解剖（源码当前真实值）
      </h3>
      <div className="mb-8">
        <CompareTable
          head={['维度', 'A 套 Dialog', 'B 套 OriginalDialog（已对齐 C 套）', 'AlertDialog（手拼底座）']}
          rows={[
            [
              '遮罩',
              'bg-black/40 + blur（浅黑毛玻璃）',
              'bg-gray-500/90 + blur（灰白毛玻璃）',
              'bg-gray-500/90 + blur（同 B）',
            ],
            ['层级 z-index', 'z-[100]', 'z-50', 'z-[110]'],
            ['圆角', 'sm:rounded-lg（8px，移动端直角）', 'rounded-2xl（16px）', 'sm:rounded-lg（8px，移动端直角）'],
            ['内边距', 'p-5（20px）', 'p-5（20px）', 'p-6（24px）'],
            [
              '边框 / 阴影',
              'border + shadow-lg',
              'border #ebebeb + 淡投影',
              '无边框、无阴影',
            ],
            [
              '标题',
              'text-base font-semibold',
              'text-base font-medium',
              '组件是 text-lg semibold，但各页多自拼标题行',
            ],
            [
              '关闭按钮 ×',
              '内置右上（可关）',
              '内置右上（可关）',
              '无内置，各页自拼',
            ],
            [
              '深色模式底色',
              'dark:bg-[#303134]（写死）',
              'bg-background（跟主题）',
              'dark:bg-gray-900',
            ],
            [
              '移动端行为',
              '居中缩放出现',
              '居中缩放出现',
              '从底部滑入、贴底',
            ],
            [
              'footer 按钮',
              '各页自拼（多为 Button outline + default）',
              '模板：取消白底描边 + 确认 danger/primary 档；直接拼的各页自理',
              '各页自拼（红 #F53F3F 等）',
            ],
          ]}
        />
      </div>

      {/* ③ Side-by-side demos — identical content, different shells */}
      <h3 className="mb-3 text-base font-semibold text-text-primary">
        ③ 同一内容装进各个壳（逐个打开对比）
      </h3>
      <div className="mb-8">
        <DemoGrid cols={3}>
          {/* A-set raw primitives — the largest population */}
          <Demo label="A 套 · 原语直接拼（22 处）" note="ui/Dialog.tsx · 浅黑毛玻璃 · 圆角8 · p-5">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline">打开</Button>
              </DialogTrigger>
              <DialogContent className="max-w-md">
                <DialogHeader>
                  <DialogTitle>弹窗标题</DialogTitle>
                  <DialogDescription>标题下的说明文字。</DialogDescription>
                </DialogHeader>
                {demoBody}
                <DialogFooter>
                  <DialogClose asChild>
                    <Button variant="outline">取消</Button>
                  </DialogClose>
                  <Button>确定</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </Demo>

          {/* A-set template — legacy default black confirm button */}
          <Demo label="A 套 · DialogTemplate（3 处）" note="旧模板 · 默认黑底确认钮 · 正文额外 px-6">
            <Dialog>
              <DialogTrigger asChild>
                <Button variant="outline">打开</Button>
              </DialogTrigger>
              <DialogTemplate
                title="弹窗标题"
                description="标题下的说明文字。"
                main={demoBody}
                selection={{ selectHandler: () => null, selectText: '确定' }}
              />
            </Dialog>
          </Demo>

          {/* B-set template — shell already aligned with C-set */}
          <Demo label="B 套 · OGDialogTemplate（16 处）" note="壳已对齐 C 套 · 圆角16 · 取消/确认已统一">
            <OGDialog>
              <OGDialogTrigger asChild>
                <Button variant="outline">打开</Button>
              </OGDialogTrigger>
              <OGDialogTemplate
                title="弹窗标题"
                description="标题下的说明文字。"
                className="max-w-md"
                main={demoBody}
                selection={{
                  selectHandler: () => null,
                  selectVariant: 'primary',
                  selectText: '确定',
                }}
              />
            </OGDialog>
          </Demo>

          {/* B-set raw primitives — same shell, hand-rolled body/footer */}
          <Demo label="B 套 · OG 原语直接拼（16 处）" note="壳同左 · 头尾各页自拼（设置/Prompts 老页面）">
            <OGDialog>
              <OGDialogTrigger asChild>
                <Button variant="outline">打开</Button>
              </OGDialogTrigger>
              <OGDialogContent className="max-w-md">
                <OGDialogHeader>
                  <OGDialogTitle>弹窗标题</OGDialogTitle>
                  <OGDialogDescription>标题下的说明文字。</OGDialogDescription>
                </OGDialogHeader>
                {demoBody}
                <div className="flex justify-end gap-2">
                  <Button variant="outline">取消</Button>
                  <Button>确定</Button>
                </div>
              </OGDialogContent>
            </OGDialog>
          </Demo>

          {/* Hand-rolled AlertDialog population */}
          <Demo
            label="手拼 AlertDialog（7 处）"
            note="p-6 · 圆角8 · 无边框阴影 · z-110 · 移动端贴底滑入"
          >
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline">打开</Button>
              </AlertDialogTrigger>
              <AlertDialogContent className="max-w-md">
                {/* Business pages hand-roll header/footer like this (ChannelMemberDialog etc.) */}
                <h3 className="text-base font-medium text-text-primary">弹窗标题</h3>
                {demoBody}
                <div className="flex justify-end gap-2">
                  <Button variant="outline">取消</Button>
                  <Button>确定</Button>
                </div>
              </AlertDialogContent>
            </AlertDialog>
          </Demo>

          {/* C-set reference — the finalized confirm shell */}
          <Demo
            label="C 套 · useConfirm 参照（已定稿）"
            note="二次确认基准壳：圆角16 / p-5 / 灰底毛玻璃 —— Modal 壳候选"
          >
            <ConfirmReferenceDemo />
          </Demo>
        </DemoGrid>
      </div>

      {/* ④ Decision checklist */}
      <h3 className="mb-3 text-base font-semibold text-text-primary">④ 待设计师定夺</h3>
      <div className="rounded-xl border border-border-light bg-muted/20 p-5 text-sm leading-7 text-text-primary">
        <ol className="list-decimal space-y-1 pl-5">
          <li>
            <b>遮罩</b>：A 套浅黑毛玻璃（black/40+blur） vs B/C 套灰白毛玻璃（gray-500/90+blur）？
            （纯深色 black/80 已在二次确认期淘汰）
          </li>
          <li>
            <b>圆角</b>：8px（A 套 / AlertDialog） vs 16px（B/C 套）？移动端是否保留直角/贴底？
          </li>
          <li>
            <b>内边距</b>：p-5（20px，A/B/C） vs p-6（24px，AlertDialog）？header/body/footer 间距（当前统一 gap-4）？
          </li>
          <li>
            <b>标题</b>：font-semibold（A 套） vs font-medium（B/C 套）？
          </li>
          <li>
            <b>关闭按钮 ×</b>：样式与位置（当前 A/B 内置右上小 ×，AlertDialog 各页自拼）？
          </li>
          <li>
            <b>footer 按钮</b>：普通弹窗的取消/确定用 Button 组件（outline+default） 还是 C
            套确认弹窗那对（白底描边 + danger/primary）？按钮间距 gap-2 vs gap-3？
          </li>
          <li>
            <b>层级</b>：z-50 / z-[100] / z-[110] 三档并存，统一到几？（需盘 Drawer/Sheet/Popover 的层级关系）
          </li>
          <li>
            <b>原语收敛</b>：A 套 22 处直拼是最大人群 —— 是把 A 套壳改成标准（业务零改动），还是逐批迁 B 套？
          </li>
        </ol>
      </div>
    </Section>
  );
}
