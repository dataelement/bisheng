/**
 * Color migration ledger — DEV-ONLY.
 * The spec itself lives in the 「设计规范 → 色彩」 page; this page tracks the
 * bare-hex → semantic-token replacement work (packages/ui/docs/基础-色彩规范.mdx).
 *
 * NOTE on i18n lint budget: this file carries frozen no-restricted-syntax
 * suppressions (shrink-only). Keep Chinese copy in as FEW JSXText nodes as
 * possible — plain quotes instead of inline <code>/<b> inside sentences.
 */
import { ComponentPage, ExampleGroup, CompareTable } from '../components/kit';

export function ColorProgress() {
  return (
    <ComponentPage
      title="色彩 · 现状"
      eng="Color Inventory"
      description="两层 token + Tailwind 接线已落地（2026-07-15）。2026-07-30 灰阶统一色温（单一色相 264°，对比度零变化）并完成批量迁移：四轮 codemod 共 1548 处裸 hex 折叠进语义类——① 979 处精确同值折叠（139 文件）；② 421 处近似值折叠（拍板：#212121 → text-1、#999/#999999 → text-3、#EBECF0 → gray-3，124 文件）；③ 73 处 #ECECEC（拍板：border 角色 → border-base，bg 角色 → fill-3，42 文件）；④ 75 处 #818181/#8C8C8C → text-3（拍板：均为辅助文字/图标默认灰角色；ThinkingContent 思考正文 1 处按可读性升 text-2，34 文件）。codemod 白名单式，仅「前缀 × 色值」精确命中才改写，变体链原样保留。剩余待处理见「待迁移」表；其余近似值（#FBFBFB ×40、#F7F7F7 ×28、#1A1A1A ×22…）仍属设计决策，逐处目检。"
      whenToUse={[
        'platform 暂缓：98 处中性裸 hex 等 @bisheng/ui tokens.css 接入后同法迁移（platform 尚无语义层）。',
        '近似值折叠需设计师拍板或逐处目检，不做机械替换。',
        '游离蓝迁品牌 token 前，先核对是否属「固定蓝」例外（审批中 tag 等，永远不换肤）。',
        '命名注：规范语义名 border 与 shadcn 的 --border（HSL）及 Tailwind 边框类冲突，落地为 border-base（类 border-border-base）。',
      ]}
      bodyTitle="迁移台账"
    >
      <ExampleGroup
        title="已迁移（2026-07-30 两轮批量折叠）"
        subtitle="旧写法 → 新语义类，值同源于 design-token.cjs。带 * 的为第二轮近似值折叠（拍板）。"
      >
        <CompareTable
          head={['旧写法', '新语义类', '处数']}
          rows={[
            [<code key="o">text-[#1D2129]</code>, <code key="n">text-text-1</code>, '126'],
            [<code key="o">text-[#212121] *</code>, <code key="n">text-text-1</code>, '194'],
            [<code key="o">text-[#4E5969]</code>, <code key="n">text-text-2</code>, '190'],
            [<code key="o">text-[#86909C]</code>, <code key="n">text-text-3</code>, '263 (+3 placeholder-)'],
            [<code key="o">text-[#999999] / text-[#999] *</code>, <code key="n">text-text-3</code>, '145 (+1 placeholder-)'],
            [<code key="o">text-[#818181] / text-[#8C8C8C] *</code>, <code key="n">text-text-3</code>, '75 (1 → text-2)'],
            [<code key="o">text-[#C9CDD4]</code>, <code key="n">text-text-4</code>, '44'],
            [<code key="o">bg-[#F7F8FA] / bg-[#F8F8F8]</code>, <code key="n">bg-fill-1</code>, '78 + 17'],
            [<code key="o">bg-[#F2F3F5]</code>, <code key="n">bg-fill-2</code>, '72'],
            [<code key="o">bg-[#E5E6EB]</code>, <code key="n">bg-fill-3</code>, '32'],
            [<code key="o">bg-[#EBECF0] *</code>, <code key="n">bg-fill-3</code>, '5'],
            [<code key="o">bg-[#C9CDD4]</code>, <code key="n">bg-fill-4</code>, '7'],
            [<code key="o">border-[#E5E6EB]</code>, <code key="n">border-border-base</code>, '116 (+1 divide-)'],
            [<code key="o">border-[#EBECF0] *</code>, <code key="n">border-border-base</code>, '76'],
            [<code key="o">border/divide-[#ECECEC] *</code>, <code key="n">border-border-base</code>, '67'],
            [<code key="o">bg-[#ECECEC] *</code>, <code key="n">bg-fill-3</code>, '4 (+2 css/comment)'],
            [<code key="o">border-[#C9CDD4]</code>, <code key="n">border-border-deep</code>, '9'],
            [<code key="o">border-[#F2F3F5]</code>, <code key="n">border-fill-2</code>, '20 (+1 ring-)'],
          ]}
        />
      </ExampleGroup>

      <ExampleGroup
        title="待迁移"
        subtitle="无既有语义 token 或需人工判断，未纳入批量。"
      >
        <CompareTable
          head={['写法', '建议', '处数']}
          rows={[
            [<code key="o">text-[#A9AEB8]</code>, 'gray-5 无语义映射：目检后归 text-text-3 或 text-text-4', '14'],
            [<code key="o">bg-[#1D2129] / bg-[#212121]</code>, '拍板 2026-07-30 暂缓。8 处 = Tooltip2 调用处覆盖（基座是 bg-black，两套底色并存，收敛方向未定）；2 处 = Linsight 澄清卡近黑按钮，归 Button 迁移批次。方案备忘：BG 家族加 inverse 角色 token、改 Tooltip2 基座、删调用处覆盖', '10'],
            [<code key="o">text/bg-[#6B7785]</code>, 'gray-7 无语义映射：目检后归 text-text-2 或 text-text-3', '8'],
            [<code key="o">bg-[#999999] / bg-[#999] / border-[#212121]</code>, '文字值用作底/边，越轨用法，逐处目检', '10'],
            [<code key="o">bg-[#86909C] / text-[#E5E6EB]</code>, '越轨用法，逐处目检', '2'],
            [<code key="o">stroke="#4E5969" / "#999999" / "#818181"</code>, 'SVG 图标（channels / TxtIcon）：迁 currentColor + 外层 text 类', '34'],
            [<code key="o">INK / NARRATION_COLOR …</code>, 'JS 常量引 token 需运行时取值，单独处理', '≈5'],
            [<code key="o">#FBFBFB / #F7F7F7 / #1A1A1A …</code>, '近似值折叠，属设计决策，逐处目检', '≈160'],
          ]}
        />
      </ExampleGroup>
    </ComponentPage>
  );
}
