/** Gallery overview — DEV-ONLY. High-level status of the unification effort. */
import { ComponentPage, CompareTable } from '../components/kit';

export function OverviewSection() {
  return (
    <ComponentPage
      title="组件统一化"
      eng="Overview"
      description="把 client 前台重复、样式不一致的高频组件逐个统一，最终抽成可复用的设计组件库。本页仅开发环境可见，用户看不到。"
      whenToUse={[
        <>改这里用到的组件 = 改<b>真实业务组件</b>，全站同步生效（组件是共享的）。</>,
        <>左侧按分组选择组件，查看其现状、各档位与状态。</>,
        <>工作方式、提交规则见 <code>docs-ui-refactor/00-总纲.md</code>。</>,
      ]}
    >
      <CompareTable
        head={['组件', '状态', '现有版本', '收敛基准']}
        rows={[
          ['字体 Typography', '🟨 进行中', 'Tailwind 默认档', '九档 semantic token（已落地）'],
          ['Modal 弹窗', '🟨 进行中', '4（含 1 死代码）', '待定 · OGDialogTemplate 候选'],
          ['Button 按钮', '⬜ 待办', '1（已 cva 化，较好）', 'Button.tsx'],
          ['Select / 下拉', '⬜ 待办', '多个', '待定'],
          ['Dropdown 菜单', '⬜ 待办', '2', '待定'],
        ]}
      />
    </ComponentPage>
  );
}
