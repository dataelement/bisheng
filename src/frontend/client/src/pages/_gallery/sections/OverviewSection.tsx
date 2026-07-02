/** Gallery overview — DEV-ONLY. High-level status of the unification effort. */
import { Section, CompareTable } from '../components/kit';

export function OverviewSection() {
  return (
    <Section
      id="overview"
      title="组件统一化 · 总览"
      subtitle="本页仅在开发环境可见，用户看不到。改这里用到的组件 = 改真实业务组件，全站同步生效。"
    >
      <p className="mb-4 max-w-3xl text-sm text-text-primary">
        目标：把 client 前台重复、样式不一致的高频组件逐个统一，最终抽成可复用的设计组件库。
        工作方式见 <code>docs-ui-refactor/00-总纲.md</code>。左侧选择组件查看现状与各档位。
      </p>
      <CompareTable
        head={['组件', '状态', '现有版本', '收敛基准']}
        rows={[
          ['Modal 弹窗', '🟨 进行中', '4（含 1 死代码）', '待定 · OGDialogTemplate 候选'],
          ['Select / 下拉', '⬜ 待办', '多个', '待定'],
          ['Button 按钮', '⬜ 待办', '1（已 cva 化，较好）', 'Button.tsx'],
          ['Dropdown 菜单', '⬜ 待办', '2', '待定'],
        ]}
      />
    </Section>
  );
}
