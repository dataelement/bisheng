/**
 * Progress overview — DEV-ONLY. The migration dashboard for the unification
 * effort's owner. Spec consumers (designers/engineers/PMs) should use the
 * 「设计规范」 mode instead; this board mirrors docs-ui-refactor/00-总纲.md §四.
 */
import { ComponentPage, CompareTable } from '../components/kit';

export function ProgressOverview() {
  return (
    <ComponentPage
      title="迁移进度"
      eng="Progress"
      description={
        <>
          组件统一化的现状看板，给改造负责人看。左侧各组件页是对应的迁移账本（用量盘点 /
          旧写法清单 / 待定项）。只想查规范怎么用？切回顶部的「设计规范」。
        </>
      }
      whenToUse={[
        <>工作方式、双窗口提交规则见 <code>docs-ui-refactor/00-总纲.md</code>。</>,
        <>
          画廊卫生规则：旧写法在业务里<b>清零即删 demo 卡</b>，清单表保留一行「0（原 N）✅」作台账；
          旧组件整体退役后，该组件页从"现状病历"瘦身为纯规范文档。
        </>,
        <>状态点：🟨 进行中 · ⬜ 待办 · ✅ 完成；优先级由设计师逐个指定（当前：Modal → Select）。</>,
      ]}
      bodyTitle="进度看板"
    >
      <CompareTable
        head={['组件', '状态', '现状', '基准（收敛目标）与剩余工作']}
        rows={[
          [
            '字体 Typography',
            '🟨 进行中',
            'Tailwind 默认档',
            '九档 semantic token + 系统字体栈已落地；剩：删死字体 / typography.css / 逐步迁移',
          ],
          [
            '色彩 Colors',
            '🟨 进行中',
            '裸 hex 2469 处 / 215 值（2026-07-14 扫描）',
            'Arco 两层 token 已落地；剩：逐批迁移（第一优先 = LibreChat 语义 token 重指向 Arco 值）',
          ],
          [
            '多端适配 Responsive',
            '🟨 v1 已建',
            '移动端处理散落各组件',
            '双判定口径 + 4 原则已定；组件细则随各组件文档补充',
          ],
          [
            '滚动条 Scrollbar',
            '✅ 完成',
            '原全局强制细滚动条（已移除）',
            '跟随系统设置已落地（2026-07-15）；剩：.scrollbar-os 空类 ~33 处随手清、灵思深色面板例外待定夺',
          ],
          [
            'Button 按钮',
            '🟨 进行中',
            '5 路并行（旧 API 已自动映射）',
            'color×variant 双轴 v1 已落地；剩：设计师验收 → 逐批迁移 → 清退 btn 系全局类',
          ],
          [
            'Modal 弹窗',
            '🟨 进行中',
            '5 个并行体系 · 约 64 个业务文件',
            '标准待定 · C 套壳为基准候选（见 Modal 迁移页「待设计师定夺」）',
          ],
          [
            '二次确认弹窗',
            '🟨 进行中',
            '2 套体系（真确认已全部迁 C 套）',
            'B 套壳与按钮已对齐 C 套；剩：死 UI 清理、表单弹窗归 Modal 期',
          ],
          ['点赞 / 点踩', '✅ 完成', '1（已统一）', 'MessageFeedbackButtons 全 6 类回答界面共用'],
          ['Select / 下拉', '⬜ 待办', '多个', '待定（下一个优先）'],
          ['Dropdown 菜单', '⬜ 待办', '2（Dropdown / DropdownMenu）', '待定'],
          ['Input 输入框', '⬜ 待办', '待扫描', '待定'],
          ['Tabs 标签页', '⬜ 待办', '待扫描', '待定'],
        ]}
      />
    </ComponentPage>
  );
}
