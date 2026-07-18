/**
 * Confirm dialog migration ledger — DEV-ONLY. See docs-ui-refactor/组件-Modal弹窗.md.
 *
 * Tracks the OGDialogTemplate-selection → useConfirm() convergence: population
 * table, the 9 historical selectClasses variants, and old-API demos that should
 * now render with the unified look (step-1 convergence acceptance). The finalized
 * spec lives in 「设计规范 → 二次确认弹窗」.
 */
import { ReactNode } from 'react';
import { Button } from '~/components/ui/Button';
import { OGDialog, OGDialogTrigger } from '~/components/ui/OriginalDialog';
import OGDialogTemplate from '~/components/ui/OGDialogTemplate';
import { Label } from '~/components/ui/Label';
import { ComponentPage, ExampleGroup, Demo, DemoGrid, CompareTable } from '../components/kit';

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
            <Label className="text-left text-body font-medium">{body}</Label>
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

export function ConfirmProgress() {
  return (
    <ComponentPage
      title="二次确认 · 迁移"
      eng="Confirm Progress"
      description={
        <>
          两套体系：旧页面走 <code>OGDialogTemplate selection</code>（剩 13 文件：7 处死 UI 确认 +
          6 处表单弹窗），新页面走 <code>useConfirm()</code>（26 文件，含已迁入的 10 处）。
          <b>用户可见的真确认已全部迁完</b>；死 UI（被注释的 SidePanel 树 + 无人引用的
          Chat/Header 树）待死代码清理，表单弹窗归 Modal 期。<b>收敛第一步已完成</b>：B
          套壳与按钮已对齐 C 套，历史 9 种 selectClasses 被自动折叠为 danger / primary 两档 ——
          下方旧写法卡片现在应呈现统一外观，逐个打开即是验收。 （另有 9 个文件手拼{' '}
          <code>AlertDialog</code> —— 属于普通弹窗，归 Modal 改造范围，本期不动。）
        </>
      }
      whenToUse={[
        <>剩余工作：死 UI 清理（selectClasses ①②③ 全在死树）；宽度与 Loading 待定项随第三步迁移清理。</>,
        <>画廊卫生：某写法业务清零后删卡片，清单表留「0（原 N）✅」台账。</>,
      ]}
      bodyTitle="现状盘点"
    >
      {/* The two coexisting confirm-dialog systems */}
      <ExampleGroup title="现状：两套确认体系">
        <CompareTable
          head={['体系', '实现', '业务文件数', '用在哪', '样式一致性']}
          rows={[
            [
              'B 套模板',
              <>
                <code>OGDialogTemplate</code> + <code>selection</code>
              </>,
              '13（原 21；剩余全是死 UI 或表单）',
              '旧页面（会话/书签/Agent/设置/Prompt…LibreChat 血统）',
              '差 · 确认按钮 9 种写法',
            ],
            [
              'C 套服务',
              <>
                <code>useConfirm()</code>（ConfirmContext + AlertDialog）
              </>,
              '26（收敛完成，含已迁入 10 处）',
              '新页面（知识空间 / 订阅频道 / 权限）',
              '好 · 样式集中在一个文件，destructive/default 两档',
            ],
          ]}
        />
      </ExampleGroup>

      {/* Inventory table: every selectClasses variant found in business code */}
      <ExampleGroup title="确认按钮 selectClasses 清单（9 种历史写法）">
        <CompareTable
          head={['#', '确认按钮 selectClasses（原文）', '用处', '文件数']}
          rows={[
            [
              '1',
              <code key="c">bg-red-700 dark:bg-red-600 hover:bg-red-800 …</code>,
              '可达的 4 处已迁 C；剩 4 处全是死 UI（书签/分享弹窗/两个工具移除）',
              '4（原 8）· 全死 UI',
            ],
            [
              '2',
              <code key="c">bg-red-600 hover:bg-red-700 dark:hover:bg-red-800</code>,
              '删除 Agent / Assistant —— 死 UI（SidePanel 被注释）',
              '2（原 3）· 全死 UI',
            ],
            [
              '3',
              <code key="c">bg-red-600 hover:bg-red-700 dark:hover:bg-red-600</code>,
              '清空预设 —— 死 UI（Chat/Header 无人引用）',
              '1 · 死 UI',
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
              '删除版本 / 管理员确认 —— ✅ 已全部迁 C 套',
              '0（原 2）',
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
      </ExampleGroup>

      <ExampleGroup title="逐个打开对比（旧写法现应呈现统一外观）">
        <DemoGrid cols={3}>
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
          label="② red-600 系（2 处，原 3）"
          note="删除 Agent — SidePanel/Agents/DeleteButton.tsx"
          title="删除助手"
          body="确定要删除这个助手吗？此操作不可撤销。"
          selectText="删除"
          selectClasses="bg-red-600 hover:bg-red-700 dark:hover:bg-red-800 text-white"
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
          note="模板内置 Spinner · 各页自塞 Spinner 的写法已随迁移清零（原 4 处）"
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
      </ExampleGroup>
    </ComponentPage>
  );
}
