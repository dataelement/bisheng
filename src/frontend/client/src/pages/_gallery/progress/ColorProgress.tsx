/**
 * Color migration ledger — DEV-ONLY.
 * The spec itself lives in the 「设计规范 → 色彩」 page; this page tracks the
 * bare-hex → semantic-token replacement work (docs-ui-refactor/基础-色彩规范.md).
 */
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

export function ColorProgress() {
  return (
    <ComponentPage
      title="色彩 · 迁移"
      eng="Color Progress"
      description={
        <>
          两层 token + Tailwind 接线已落地（2026-07-15）。现状：裸 hex <b>2469 处 / 215 个值</b>
          （2026-07-14 扫描）。本轮只搭 token 不批量迁移，随组件改造与设计师点名逐步替换。
        </>
      }
      whenToUse={[
        <>
          <b>第一优先</b>：把 LibreChat 语义 token（<code>--text-primary</code> 等）重指向 Arco
          值，一次改变量全站生效（色彩规范附录 A.3 #5，本轮未做）。
        </>,
        <>近似值折叠（如 <code>#EBECF0</code> → gray-3，视觉差 ≤2/255）需逐处目检。</>,
        <>游离蓝迁品牌 token 前，先核对是否属「固定蓝」例外（审批中 tag 等，永远不换肤）。</>,
        <>
          命名注：规范里的语义名 <code>border</code> 与 shadcn 的 <code>--border</code>（HSL）及
          Tailwind 边框类冲突，落地为 <code>border-base</code>（类{' '}
          <code>border-border-base</code>，与现有 <code>border-border-light</code> 同构）。
        </>,
      ]}
      bodyTitle="迁移台账"
    >
      <ExampleGroup title="迁移速查" subtitle="旧写法 → 新语义类。">
        <CompareTable
          head={['旧写法', '新语义类', '说明']}
          rows={[
            [<code key="o">#1D2129 / #212121</code>, <code key="n">text-text-1</code>, 'Arco gray-10 / LibreChat gray-800 → 主文字'],
            [<code key="o">#4E5969</code>, <code key="n">text-text-2</code>, 'Arco gray-8 → 次文字（×197）'],
            [<code key="o">#86909C / #999999 / text-gray-500</code>, <code key="n">text-text-3</code>, '辅助文字（#86909C 全站最高频 ×263）'],
            [<code key="o">#C9CDD4</code>, <code key="n">text-text-4 / bg-fill-4</code>, '禁用文字 / 重填充，按语境选'],
            [<code key="o">#E5E6EB / #EBECF0 / #ECECEC</code>, <code key="n">border-border-base</code>, '#EBECF0(×81) 折叠进 gray-3，视觉差 ≤2/255，逐处目检'],
            [<code key="o">#F7F8FA / #F2F3F5</code>, <code key="n">bg-fill-1 / bg-fill-2</code>, 'hover 底 / filled 控件底'],
            [<code key="o">#00C650 / #06B84C / #007D1A</code>, <code key="n">success 系</code>, '野生成功绿折叠（集中在 Files/VectorStore 旧组件）'],
            [<code key="o">red-500 / --destructive / surface-destructive</code>, <code key="n">danger 系</code>, '危险红 4 写法收敛到 #F53F3F 三态'],
            [<code key="o">#FFF2F0</code>, <code key="n">bg-danger-tint</code>, '旧浅红 tag 底 → Arco red-1 #FFECE8'],
            [<code key="o">#335CFF / #0072FF / #1B61E6 / #165DFF 硬编码</code>, <code key="n">blue-* / --brand-*</code>, '游离蓝迁品牌 token，先核对是否属固定蓝例外'],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
