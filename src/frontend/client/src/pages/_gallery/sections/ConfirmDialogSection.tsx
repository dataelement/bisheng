/**
 * Confirm dialog gallery — DEV-ONLY. See docs-ui-refactor/组件-Modal弹窗.md.
 *
 * "二次确认弹窗" = OGDialogTemplate with the `selection` prop (delete / dangerous
 * action confirmations). Every demo below reproduces an exact selectClasses string
 * found in business code, so the designer can compare the current zoo of confirm
 * button styles and pick one standard.
 */
import { ReactNode } from 'react';
import { Button } from '~/components/ui/Button';
import { OGDialog, OGDialogTrigger } from '~/components/ui/OriginalDialog';
import OGDialogTemplate from '~/components/ui/OGDialogTemplate';
import { Label } from '~/components/ui/Label';
import { useConfirm } from '~/Providers';
import { Section, Demo, DemoGrid, CompareTable } from '../components/kit';

/** Demos for the app-wide `useConfirm()` service (ConfirmContext, AlertDialog-based). */
function UseConfirmDemos() {
  const confirm = useConfirm();
  return (
    <>
      <Demo
        label="C 套 · useConfirm 危险态"
        note="ConfirmContext.tsx · variant: destructive · 红图标+红标题+暂不/确认删除"
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
      </Demo>
      <Demo
        label="C 套 · useConfirm 普通态"
        note="ConfirmContext.tsx · variant: default · 橙色警示图标+主色确认"
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
      </Demo>
    </>
  );
}

/** One confirm-dialog demo replicating a real business usage. */
function ConfirmDemo({
  label,
  note,
  title,
  body,
  selectText,
  selectClasses,
  isLoading,
  showCloseButton = false,
}: {
  label: string;
  note?: string;
  title: string;
  body: ReactNode;
  selectText: string;
  selectClasses?: string;
  isLoading?: boolean;
  showCloseButton?: boolean;
}) {
  return (
    <Demo label={label} note={note}>
      <OGDialog>
        <OGDialogTrigger asChild>
          <Button variant="outline">打开</Button>
        </OGDialogTrigger>
        <OGDialogTemplate
          showCloseButton={showCloseButton}
          title={title}
          className="max-w-[450px]"
          main={
            <Label className="text-left text-sm font-medium">{body}</Label>
          }
          selection={{
            selectHandler: () => undefined,
            selectClasses,
            selectText,
            isLoading,
          }}
        />
      </OGDialog>
    </Demo>
  );
}

export function ConfirmDialogSection() {
  return (
    <Section
      id="confirm"
      title="二次确认弹窗"
      subtitle={
        <>
          删除/危险操作时的「确认 / 取消」小弹窗。两套体系：旧页面走{' '}
          <code>OGDialogTemplate selection</code>（剩 16 文件），新页面走 <code>useConfirm()</code>
          （21 文件，含已迁入的 5 处）。<b>收敛第一步已完成</b>：B 套壳与按钮已对齐 C 套，历史 9 种 selectClasses
          被自动折叠为 danger / primary 两档 —— 下方旧写法卡片现在应呈现统一外观，逐个打开即是验收。
          （另有 9 个文件手拼 <code>AlertDialog</code> —— 属于普通弹窗，归 Modal 改造范围，本期不动。）
        </>
      }
    >
      {/* The three coexisting confirm-dialog systems */}
      <div className="mb-6">
        <CompareTable
          head={['体系', '实现', '业务文件数', '用在哪', '样式一致性']}
          rows={[
            [
              'B 套模板',
              <>
                <code>OGDialogTemplate</code> + <code>selection</code>
              </>,
              '16（原 21，迁移中）',
              '旧页面（会话/书签/Agent/设置/Prompt…LibreChat 血统）',
              '差 · 确认按钮 9 种写法',
            ],
            [
              'C 套服务',
              <>
                <code>useConfirm()</code>（ConfirmContext + AlertDialog）
              </>,
              '21（收敛目标，含已迁入 5 处）',
              '新页面（知识空间 / 订阅频道 / 权限）',
              '好 · 样式集中在一个文件，destructive/default 两档',
            ],
          ]}
        />
      </div>

      {/* Inventory table: every selectClasses variant found in business code */}
      <div className="mb-6">
        <CompareTable
          head={['#', '确认按钮 selectClasses（原文）', '用处', '文件数']}
          rows={[
            [
              '1',
              <code key="c">bg-red-700 dark:bg-red-600 hover:bg-red-800 …</code>,
              '删除（书签/工具/分享链接…）· 删会话 2 处已迁 C',
              '6（原 8）',
            ],
            [
              '2',
              <code key="c">bg-red-600 hover:bg-red-700 dark:hover:bg-red-800</code>,
              '删除（Agent / Assistant / Prompt 组）',
              '3',
            ],
            [
              '3',
              <code key="c">bg-red-600 hover:bg-red-700 dark:hover:bg-red-600</code>,
              '清空预设',
              '1',
            ],
            [
              '4',
              <code key="c">bg-destructive hover:bg-destructive/80</code>,
              '清空聊天 / 删缓存 / 撤销密钥 —— ✅ 已全部迁 C 套',
              '0（原 3）',
            ],
            [
              '5',
              <code key="c">bg-surface-destructive hover:bg-surface-destructive-hover</code>,
              '删除版本 / 管理员确认',
              '2',
            ],
            [
              '6',
              <code key="c">bg-green-500 hover:bg-green-600 text-white</code>,
              '保存预设 / 保存 API Key（确认=绿色?!）',
              '2',
            ],
            [
              '7',
              <>
                <code>btn btn-primary</code>（全局 CSS 类）
              </>,
              '提交密钥',
              '1',
            ],
            [
              '8',
              <code key="c">bg-surface-submit hover:bg-surface-submit-hover</code>,
              '重命名保存',
              '1',
            ],
            [
              '9',
              <>
                （不传 → 模板默认）<code>bg-gray-800 … dark:bg-gray-200</code>
              </>,
              'OGDialogTemplate 内置 defaultSelect',
              '—',
            ],
          ]}
        />
      </div>

      {/* Anatomy after step-1 convergence — B shell/buttons now mirror the C look */}
      <div className="mb-6">
        <CompareTable
          head={['部位', '对齐后的值（B 套 = C 套）', '备注']}
          rows={[
            [
              '弹窗容器',
              <code key="c">rounded-2xl p-5 gap-4 border #ebebeb + 淡投影</code>,
              '圆角 16 / padding 20，与 C 套一致',
            ],
            [
              '遮罩',
              <>
                <code>bg-gray-500/90</code> + <code>backdrop-blur-md</code>
              </>,
              '灰底毛玻璃，与 C 套一致',
            ],
            ['标题', <code key="c">text-base font-medium leading-6</code>, '与 C 套一致'],
            [
              '确认按钮',
              <>
                两档：danger <code>#f53f3f</code> / primary 品牌主色（<code>selectVariant</code>{' '}
                指定，旧 selectClasses 自动折叠，未识别的原样放行）
              </>,
              'cva 档位 · 特例走 selectClasses 口子',
            ],
            [
              '取消按钮',
              <>
                白底描边 <code>hover:bg-[#f7f8fa]</code>，<code>focus-visible</code> 焦点环
              </>,
              '与 C 套一致（含知识空间同款 hover）',
            ],
            [
              '待定项',
              '宽度仍由各页传（max-w-[450px]/max-w-lg vs C 套 400px）；Loading 仍有 4 处页面自塞 Spinner',
              '随第三步迁移一并清理',
            ],
          ]}
        />
      </div>

      <DemoGrid cols={3}>
        <UseConfirmDemos />
        <ConfirmDemo
          label="① red-700 系（6 处，原 8）"
          note="删除书签 — Bookmarks/DeleteBookmarkButton.tsx（原例子删会话已迁 C 套）"
          title="删除书签"
          body={
            <>
              确认删除书签 <strong>「工作」</strong>？
            </>
          }
          selectText="删除"
          selectClasses="bg-red-700 dark:bg-red-600 hover:bg-red-800 dark:hover:bg-red-800 text-white"
        />
        <ConfirmDemo
          label="② red-600 系（3 处）"
          note="删除 Agent — SidePanel/Agents/DeleteButton.tsx"
          title="删除助手"
          body="确定要删除这个助手吗？此操作不可撤销。"
          selectText="删除"
          selectClasses="bg-red-600 hover:bg-red-700 dark:hover:bg-red-800 text-white"
        />
        <ConfirmDemo
          label="⑤ surface-destructive 系（2 处）"
          note="删除版本 — Prompts/DeleteVersion.tsx"
          title="删除版本"
          body="确定要删除该 Prompt 版本吗？"
          selectText="删除"
          selectClasses="bg-surface-destructive hover:bg-surface-destructive-hover transition-colors duration-200 text-white"
        />
        <ConfirmDemo
          label="⑥ 绿色确认（2 处）"
          note="保存预设 — Endpoints/SaveAsPresetDialog.tsx"
          title="另存为预设"
          body="将当前配置保存为预设？"
          selectText="保存"
          selectClasses="bg-green-500 hover:bg-green-600 dark:hover:bg-green-600 text-white"
          showCloseButton
        />
        <ConfirmDemo
          label="⑨ 模板默认（不传 selectClasses）"
          note="OGDialogTemplate 内置 defaultSelect：黑底/暗色反白"
          title="确认操作"
          body="这是不传 selectClasses 时的默认确认按钮。"
          selectText="确认"
        />
        <ConfirmDemo
          label="Loading 态（isLoading: true）"
          note="模板内置 Spinner · 自塞 Spinner 的只剩 SharedLinks 1 处（原 4 处，3 处已迁 C）"
          title="删除会话"
          body="确认按钮处于加载中。"
          selectText="删除"
          selectClasses="bg-red-700 dark:bg-red-600 hover:bg-red-800 dark:hover:bg-red-800 text-white"
          isLoading
        />
        <ConfirmDemo
          label="⑧ surface-submit（1 处）"
          note="重命名保存 — Prompts/Groups/DashGroupItem.tsx"
          title="重命名"
          body="保存新的名称？"
          selectText="保存"
          selectClasses="bg-surface-submit hover:bg-surface-submit-hover text-white disabled:hover:bg-surface-submit"
        />
        <ConfirmDemo
          label="⑦ btn btn-primary（1 处）"
          note="提交密钥 — SetKeyDialog.tsx · 走全局 CSS 类"
          title="设置密钥"
          body="提交这个 API Key？"
          selectText="提交"
          selectClasses="btn btn-primary"
        />
      </DemoGrid>
    </Section>
  );
}
