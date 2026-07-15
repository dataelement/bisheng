/**
 * Button gallery — DEV-ONLY.
 * Standard-usage documentation for the refactored dual-axis Button
 * (docs-ui-refactor/组件-Button按钮.md v1): color × variant × size matrix,
 * states and content forms. Legacy-API mapping ledger: progress/ButtonProgress.tsx.
 */
import { Outlined } from 'bisheng-icons';
import { Button } from '~/components/ui/Button';
import {
  ComponentPage,
  ExampleGroup,
  ExampleGrid,
  ExampleCard,
  CompareTable,
} from '../components/kit';

const COLORS = ['primary', 'default', 'danger'] as const;
const VARIANTS = ['solid', 'outlined', 'filled', 'text', 'link'] as const;
const SIZES = ['small', 'medium', 'large'] as const;

const SIZE_META: Record<(typeof SIZES)[number], string> = {
  small: '高 24px · 字号 14/22 · 圆角 4px — 表格行内、紧凑工具条',
  medium: '高 32px · 字号 14/22 · 圆角 6px — 默认，绝大多数场景',
  large: '高 40px · 字号 16/24 · 圆角 8px — 登录页、大表单提交',
};

export function ButtonSection() {
  return (
    <ComponentPage
      title="Button 按钮"
      eng="Button"
      description={
        <>
          antd 式 <code>color × variant</code> 双轴：color 管颜色（primary 品牌 / default
          中性 / danger 危险），variant 管画法（solid / outlined / filled / text /
          link），3×5 组合自动成立。颜色全部走 token（品牌随蓝⇄绿主题，危险红固定），
          触屏下自动禁用 hover 态并扩 44px 热区。规范见 docs-ui-refactor/组件-Button按钮.md。
        </>
      }
      whenToUse={[
        <>
          一个操作区域只放一个 <code>primary solid</code> 主按钮；次级操作用默认按钮（
          <code>color=&quot;default&quot;</code>，白底灰描边）。
        </>,
        <>
          尺寸只用 <code>small / medium / large</code> 三档（24/32/40px），不要手写高度、
          内边距、圆角；同一视图内相邻按钮必须同尺寸。
        </>,
        <>
          弹窗 footer 右对齐、主按钮在最右（间距 12px）；页面级操作区主按钮在左首位（间距
          8px）。
        </>,
        <>
          纯 icon 按钮必须带 Tooltip 与 <code>aria-label</code>；正圆形（
          <code>shape=&quot;circle&quot;</code>）仅限纯 icon 按钮；图标 bisheng-icons
          优先，lucide 兜底。
        </>,
        <>
          loading 用组件内置的 <code>loading</code> 属性，禁止业务页自塞 Spinner；两个汉字的
          按钮不加中间空格。
        </>,
        <>
          特殊一次性样式用 <code>className</code> 覆盖，不要新增变体；旧
          API（outline/ghost/submit…）已自动映射为新双轴，读旧代码时按映射理解即可（台账见「迁移进度 →
          Button」）。
        </>,
      ]}
    >
      <ExampleGroup
        title="常用类型（§1）"
        subtitle="双轴组合的六个常用别名；其余组合按双轴自然推导。"
      >
        <ExampleGrid cols={3}>
          <ExampleCard title="Primary 主按钮" description="primary × solid — 主行动点，一个区域只放一个">
            <Button color="primary" variant="solid">
              主按钮
            </Button>
          </ExampleCard>
          <ExampleCard title="Secondary 次强调" description="primary × filled — 品牌浅底，弱于主按钮">
            <Button color="primary" variant="filled">
              次强调
            </Button>
          </ExampleCard>
          <ExampleCard title="Default 默认按钮" description="default × outlined — 最常用的次级按钮（取消/返回）">
            <Button color="default" variant="outlined">
              取消
            </Button>
          </ExampleCard>
          <ExampleCard title="Text 文字按钮" description="default × text — 最次级、表格行内、工具栏">
            <Button color="default" variant="text">
              文字按钮
            </Button>
          </ExampleCard>
          <ExampleCard title="Link 链接按钮" description="primary × link — 导航型操作，hover 不加底">
            <Button color="primary" variant="link">
              链接按钮
            </Button>
          </ExampleCard>
          <ExampleCard title="Danger 危险按钮" description="danger × solid / outlined / text — 一般配二次确认">
            <Button color="danger" variant="solid">
              删除
            </Button>
            <Button color="danger" variant="outlined">
              删除
            </Button>
            <Button color="danger" variant="text">
              删除
            </Button>
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup
        title="color × variant 全矩阵"
        subtitle="15 种组合全部成立；直接在此悬停体验 hover 色板（§5.2）。active 深一档仅触屏生效——桌面按下沿用 hover 色，不闪。"
      >
        <CompareTable
          head={['variant \\ color', 'primary 品牌', 'default 中性', 'danger 危险']}
          rows={VARIANTS.map((v) => [
            <code key="v">{v}</code>,
            ...COLORS.map((c) => (
              <Button key={c} color={c} variant={v}>
                按钮
              </Button>
            )),
          ])}
        />
      </ExampleGroup>

      <ExampleGroup
        title="尺寸 size（§2）"
        subtitle="三档：24 / 32 / 40px，圆角 4 / 6 / 8px；描边与无边框变体水平 padding 视觉等宽。"
      >
        <ExampleGrid cols={3}>
          {SIZES.map((s) => (
            <ExampleCard key={s} title={`size="${s}"`} description={SIZE_META[s]}>
              <Button color="primary" size={s}>
                按钮
              </Button>
              <Button color="default" size={s}>
                按钮
              </Button>
              <Button color="default" size={s} iconOnly aria-label="搜索">
                <Outlined.Search />
              </Button>
            </ExampleCard>
          ))}
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup
        title="内容形态（§3）"
        subtitle="纯文字 / 纯 icon / 文字 + icon；一个按钮最多一个 icon。"
      >
        <ExampleGrid cols={2}>
          <ExampleCard
            title="纯文字"
            description="不换行不省略；两个汉字不加中间空格；字重 400（全尺寸全类型一致）"
          >
            <Button>确定</Button>
            <Button color="default">取消</Button>
          </ExampleCard>
          <ExampleCard
            title="纯 icon（shape square / circle）"
            description="24/32/40，icon 14/16/18px；circle 正圆仅限纯 icon 按钮；必须带 Tooltip + aria-label，触屏热区自动扩到 ≥44px"
          >
            <Button color="default" variant="outlined" size="small" iconOnly aria-label="编辑">
              <Outlined.Edit />
            </Button>
            <Button color="default" variant="outlined" size="medium" iconOnly aria-label="编辑">
              <Outlined.Edit />
            </Button>
            <Button color="default" variant="outlined" size="large" iconOnly aria-label="编辑">
              <Outlined.Edit />
            </Button>
            <Button
              color="default"
              variant="outlined"
              shape="circle"
              iconOnly
              aria-label="搜索"
            >
              <Outlined.Search />
            </Button>
            <Button shape="circle" iconOnly aria-label="发送">
              <Outlined.Send />
            </Button>
            <Button color="default" variant="text" iconOnly aria-label="删除">
              <Outlined.Delete />
            </Button>
            <Button color="danger" variant="text" iconOnly aria-label="删除">
              <Outlined.Delete />
            </Button>
          </ExampleCard>
          <ExampleCard
            title="文字 + icon（icon 属性，默认在左）"
            description="icon 与纯 icon 同一套 14/16/18px，间距 8px（small 4px）"
          >
            <Button icon={<Outlined.Plus />}>新建</Button>
            <Button color="default" icon={<Outlined.Download />}>
              下载
            </Button>
            <Button color="danger" variant="outlined" icon={<Outlined.Delete />}>
              删除
            </Button>
          </ExampleCard>
          <ExampleCard
            title="方向语义 icon 在右"
            description="“下一步 →”类方向语义可放右侧：icon 走 children 尾部"
          >
            <Button>
              下一步
              <Outlined.ArrowRight />
            </Button>
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

      <ExampleGroup
        title="状态 state（§5）"
        subtitle="hover 请在上方矩阵直接体验；active 深一档仅触屏生效（桌面按下=hover 色，避免点击闪动）；disabled 与 loading 全类型统一；focus 环仅键盘（Tab）可见，环色随 color。"
      >
        <ExampleGrid cols={2}>
          <ExampleCard
            title="disabled（全类型统一）"
            description="灰底 rgba(0,0,0,.04) + 字 rgba(0,0,0,.25) + 边 #d9d9d9，cursor: not-allowed"
          >
            <Button disabled>主按钮</Button>
            <Button color="primary" variant="filled" disabled>
              次强调
            </Button>
            <Button color="default" disabled>
              默认
            </Button>
            <Button color="default" variant="text" disabled>
              文字
            </Button>
            <Button color="danger" disabled>
              删除
            </Button>
          </ExampleCard>
          <ExampleCard
            title="loading（内置 spinner）"
            description="spinner 顶替 icon 位、整体 opacity .65、期间不可点；禁止业务页自塞 Spinner"
          >
            <Button loading>提交中</Button>
            <Button color="default" loading>
              提交中
            </Button>
            <Button color="danger" loading>
              删除中
            </Button>
            <Button loading icon={<Outlined.Plus />}>
              新建
            </Button>
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>

    </ComponentPage>
  );
}
