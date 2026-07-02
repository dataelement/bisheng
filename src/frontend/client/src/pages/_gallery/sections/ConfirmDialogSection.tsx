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
import { Section, Demo, DemoGrid, CompareTable } from '../components/kit';

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
          删除/危险操作时的「确认 / 取消」小弹窗，全部走 <code>OGDialogTemplate</code> 的{' '}
          <code>selection</code> 用法（<b>21 个业务文件</b>）。确认按钮样式由各页面用{' '}
          <code>selectClasses</code> 自带 —— 目前存在 <b>9 种写法</b>。下面每个卡片都复刻业务里的真实写法，逐个打开对比。
        </>
      }
    >
      {/* Inventory table: every selectClasses variant found in business code */}
      <div className="mb-6">
        <CompareTable
          head={['#', '确认按钮 selectClasses（原文）', '用处', '文件数']}
          rows={[
            [
              '1',
              <code key="c">bg-red-700 dark:bg-red-600 hover:bg-red-800 …</code>,
              '删除（会话/书签/工具/分享链接…）',
              '8 · 最多',
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
              '清空聊天 / 删缓存 / 撤销密钥',
              '3',
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

      {/* Current anatomy — the hardcoded values the designer needs to re-decide */}
      <div className="mb-6">
        <CompareTable
          head={['部位', '当前写死的值', '出处']}
          rows={[
            ['弹窗容器', <code key="c">rounded-2xl p-6 gap-4 shadow-lg</code>, 'OriginalDialog.tsx'],
            [
              '遮罩',
              <>
                <code>bg-black/80</code>（无模糊）
              </>,
              'OriginalDialog.tsx',
            ],
            ['标题', <code key="c">text-lg font-semibold</code>, 'OriginalDialog.tsx'],
            [
              '正文区',
              <>
                <code>px-0 py-2</code>（各页再自带 Label 样式）
              </>,
              'OGDialogTemplate.tsx',
            ],
            [
              '按钮排布',
              <code key="c">footer 右对齐 · gap-3 · 取消在左确认在右（移动端反转）</code>,
              'OGDialogTemplate.tsx',
            ],
            [
              '确认按钮',
              <code key="c">h-10 rounded-lg px-4 py-2 text-sm</code>,
              'OGDialogTemplate.tsx（颜色由各页 selectClasses 传入）',
            ],
            [
              '取消按钮',
              <>
                <code>btn btn-neutral rounded-lg text-sm</code>（全局 CSS 类，非 Button 组件）
              </>,
              'OGDialogTemplate.tsx',
            ],
            [
              '宽度',
              <>
                <code>w-11/12</code> + 各页自带 <code>max-w-[450px]</code> /{' '}
                <code>max-w-lg</code>
              </>,
              '各业务页',
            ],
            [
              'Loading',
              '两种写法并存：selection.isLoading（模板内置 Spinner）vs 各页自己把 Spinner 塞进 selectText',
              '不统一',
            ],
          ]}
        />
      </div>

      <DemoGrid cols={3}>
        <ConfirmDemo
          label="① red-700 系（8 处 · 最多）"
          note="删除会话 — ConvoOptions/DeleteButton.tsx 原样复刻"
          title="删除会话"
          body={
            <>
              确认删除该会话？<strong>「与 Claude 的对话」</strong>
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
          label="④ bg-destructive 系（3 处）"
          note="清空聊天 — SettingsTabs/Data/ClearChats.tsx"
          title="清空聊天记录"
          body="确定要清空所有聊天记录吗？此操作不可撤销。"
          selectText="删除"
          selectClasses="bg-destructive text-white transition-all duration-200 hover:bg-destructive/80"
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
          note="模板内置 Spinner · 另有 4 处是各页自己塞 Spinner"
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
