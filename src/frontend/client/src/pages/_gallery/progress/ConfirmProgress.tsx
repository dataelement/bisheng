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
      title="二次确认 · 现状"
      eng="Confirm Inventory"
      description={
        <>
          两套体系并行：旧页面走 <code>OGDialogTemplate selection</code>（<b>13 处</b>旧
          selectClasses），新页面走 <code>useConfirm()</code>（<b>26 个文件</b>）。B 套壳与按钮
          已在组件内部对齐 C 套，外观已统一 —— 但<b>业务代码一处都没迁</b>。
        </>
      }
      whenToUse={[
        <>
          新档位 <code>selectVariant</code> 业务使用数为 <b>0</b>；折叠靠的是{' '}
          <code>OGDialogTemplate</code> 内部的旧 class 自动映射。
        </>,
        <>下方卡片全部用旧 selectClasses 渲染 —— 外观应已统一，逐个打开即是验收。</>,
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
              '13 处旧 selectClasses',
              '旧页面（会话/书签/Agent/设置/Prompt…LibreChat 血统）',
              '差 · 6 种历史写法',
            ],
            [
              'C 套服务',
              <>
                <code>useConfirm()</code>（ConfirmContext + AlertDialog）
              </>,
              '26',
              '新页面（知识空间 / 订阅频道 / 权限）',
              '好 · 样式集中在一个文件，destructive/default 两档',
            ],
          ]}
        />
      </ExampleGroup>

      {/* Inventory table: every selectClasses variant found in business code */}
      <ExampleGroup
        title="确认按钮 selectClasses 清单"
        subtitle="2026-07-20 实测：业务里仍有 13 处传旧 selectClasses；新档位 selectVariant 使用数为 0。"
      >
        <CompareTable
          head={['#', '确认按钮 selectClasses（原文）', '用处', '出现处']}
          rows={[
            [
              '1',
              <code key="c">bg-red-700 dark:bg-red-600 hover:bg-red-800 …</code>,
              'Agents/Builder 的 ActionsPanel×2、AgentTool、AssistantTool、删除书签、分享链接',
              <b key="n">6</b>,
            ],
            [
              '2',
              <code key="c">bg-red-600 hover:bg-red-700 dark:hover:bg-red-800</code>,
              '删除 Agent / Assistant',
              '2',
            ],
            [
              '3',
              <code key="c">bg-red-600 hover:bg-red-700 dark:hover:bg-red-600</code>,
              '清空预设',
              '1',
            ],
            [
              '4',
              <code key="c">bg-green-500 hover:bg-green-600 …</code>,
              '保存预设 / 保存 API Key（确认=绿色?!）',
              '2',
            ],
            [
              '5',
              <>
                <code>btn btn-primary</code>（全局 CSS 类）
              </>,
              '提交密钥 SetKeyDialog',
              '1',
            ],
            [
              '6',
              <code key="c">bg-surface-submit hover:bg-surface-submit-hover</code>,
              '重命名保存 DashGroupItem',
              '1',
            ],
            [
              '—',
              <code key="c">bg-destructive / bg-surface-destructive 系</code>,
              '清空聊天 / 删缓存 / 撤销密钥 / 删除版本 / 管理员确认 —— ✅ 已全部迁 C 套',
              '0（原 5）',
            ],
          ]}
        />
        <p className="mt-3 text-body-sm text-muted-foreground">
          折叠是在 <code>OGDialogTemplate</code> 内部做的（旧 class 自动映射为 danger / primary
          两档），所以外观已统一，但<b>业务代码一处都没迁</b> —— 上面 13 处仍是旧写法。
        </p>
      </ExampleGroup>

      <ExampleGroup title="逐个打开对比（旧写法现应呈现统一外观）">
        <DemoGrid cols={3}>
        <ConfirmDemo
          label="① red-700 系（6 处）"
          note="删除书签 · 分享链接 · Agents/Builder 工具移除"
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
          label="② red-600 系（2 处）"
          note="删除 Agent — SidePanel/Agents/DeleteButton.tsx"
          title="删除助手"
          body="确定要删除这个助手吗？此操作不可撤销。"
          selectText="删除"
          selectClasses="bg-red-600 hover:bg-red-700 dark:hover:bg-red-800 text-white"
        />
        <ConfirmDemo
          label="④ 绿色确认（2 处）"
          note="保存预设 — Endpoints/SaveAsPresetDialog.tsx"
          title="另存为预设"
          body="将当前配置保存为预设？"
          selectText="保存"
          selectClasses="bg-green-500 hover:bg-green-600 dark:hover:bg-green-600 text-white"
          showCloseButton
        />
        <ConfirmDemo
          label="模板默认（不传 selectClasses）"
          note="OGDialogTemplate 内置 defaultSelect：黑底/暗色反白"
          title="确认操作"
          body="这是不传 selectClasses 时的默认确认按钮。"
          selectText="确认"
        />
        <ConfirmDemo
          label="Loading 态（isLoading: true）"
          note="模板内置 Spinner"
          title="删除会话"
          body="确认按钮处于加载中。"
          selectText="删除"
          selectClasses="bg-red-700 dark:bg-red-600 hover:bg-red-800 dark:hover:bg-red-800 text-white"
          isLoading
        />
        <ConfirmDemo
          label="⑥ surface-submit（1 处）"
          note="重命名保存 — Prompts/Groups/DashGroupItem.tsx"
          title="重命名"
          body="保存新的名称？"
          selectText="保存"
          selectClasses="bg-surface-submit hover:bg-surface-submit-hover text-white disabled:hover:bg-surface-submit"
        />
        <ConfirmDemo
          label="⑤ btn btn-primary（1 处）"
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
