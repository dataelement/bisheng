/**
 * Progress overview — DEV-ONLY. The migration dashboard for the unification
 * effort's owner. Spec consumers (designers/engineers/PMs) should use the
 * 「设计规范」 mode instead; this board mirrors docs-ui-refactor/00-总纲.md §四.
 */
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

export function ProgressOverview() {
  return (
    <ComponentPage
      title="现状总览"
      eng="Inventory"
      description={
        <>
          这个画廊的首要职能是<b>现状梳理</b>——把产品里实际存在的各种弹窗、按钮样式摆出来并排看，
          才能看清重复与不一致。左侧各页是逐组件的现状账本。文字规范已移至独立的 rspress 文档站。
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
      bodyTitle={null}
    >
      <ExampleGroup title="现状看板" subtitle="2026-07-20 全仓扫描口径；数字为业务文件/出现次数实测值。">
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
            '原生 <button> 485 处 / Button 组件 264 处 / 全局 btn 类',
            '双轴 v1 已落地，但新 color 属性业务仅 1 处使用；485 处野生 button 未收编',
          ],
          [
            'Modal 弹窗',
            '🟨 进行中',
            '5 个并行壳体系 · 63 个业务文件',
            '标准待定 · C 套壳为基准候选（见 Modal 迁移页「待设计师定夺」）',
          ],
          [
            '二次确认弹窗',
            '🟨 进行中',
            '2 套体系；业务仍有 13 处旧 selectClasses',
            'B 套壳与按钮已对齐 C 套；剩：死 UI 清理、表单弹窗归 Modal 期',
          ],
          ['点赞 / 点踩', '✅ 完成', '1（已统一）', 'MessageFeedbackButtons 全 6 类回答界面共用'],
          ['Select / 下拉', '⬜ 待办', '多个', '待定（下一个优先）'],
          ['Dropdown 菜单', '⬜ 待办', '2（Dropdown / DropdownMenu）', '待定'],
          ['Input 输入框', '⬜ 待办', '待扫描', '待定'],
          ['Tabs 标签页', '⬜ 待办', '待扫描', '待定'],
        ]}
      />
      </ExampleGroup>

      <ExampleGroup title="规范索引" subtitle="各规范页的成熟度与源文档；已定稿的直接照用，未定稿的以页内说明为准。">
        <CompareTable
          head={['规范页', '内容', '成熟度', '源文档（docs-ui-refactor/）']}
          rows={[
            ['字体 Typography', '系统字体栈 + 九档 semantic 字号 + 双字重', '✅ 已定稿落地', '基础-字体规范.md'],
            ['色彩 Colors', '两层 token：Arco primitive → semantic（文字/填充/边框/语义色）', '✅ v1 已定稿落地', '基础-色彩规范.md'],
            ['多端适配 Responsive', '双判定口径 + 四条核心原则 + 窄屏布局惯例', '✅ v1 已建', '基础-多端适配原则.md'],
            ['滚动条（并入总览 · 设计原则 ⑦）', '显隐跟随系统设置，默认不自定义 + 三个减显 utility', '✅ 已定稿落地', '基础-滚动条规范.md'],
            ['Button 按钮', 'color × variant 双轴 + 三档尺寸 + 内容形态与状态', '✅ v1 已定稿落地', '组件-Button按钮.md'],
            ['Modal 弹窗', '普通弹窗壳标准', '🟨 未定稿 · C 套壳候选', '组件-Modal弹窗.md'],
            ['二次确认弹窗', 'useConfirm() 服务 + 壳与按钮两档标准', '✅ 已定稿', '组件-Modal弹窗.md'],
            ['点赞 / 点踩', 'MessageFeedbackButtons 统一控件 + 延迟提交交互', '✅ 已定稿', '—'],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
