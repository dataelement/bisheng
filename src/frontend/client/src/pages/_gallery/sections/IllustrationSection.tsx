/**
 * Illustration section — all themed inline-SVG illustrations from
 * src/components/illustrations/, rendered side by side in the three color
 * modes (blue theme / green theme / grey draft) so the designer can audit the
 * whole set at a glance. Spec source: docs-ui-refactor/基础-色彩规范.md §5 +
 * BRAND-THEME-HANDOFF.md §3.1.
 *
 * DEV-ONLY internal tooling, never shipped (route gated by import.meta.env.DEV).
 * NOTE on literal RGB values in this file: DISPLAY-ONLY spec pins (same
 * precedent as ColorSection's swatches) — a descendant can't un-inherit
 * html.theme-green, so the blue tab pins the :root palette to stay
 * deterministic whatever global theme the viewer has switched to.
 * Business code must never hardcode illustration colors — always --illus-*.
 */
import { ComponentType, CSSProperties, useState } from 'react';
import { cn } from '~/utils';
import {
  ArticleQAIllustration,
  CrawlingIllustration,
  EmptyStateIllustration,
  ListWebLinkIllustration,
  NoPermissionIllustration,
  SuccessIllustration,
  SystemMaintenanceIllustration,
} from '~/components/illustrations';
import { ComponentPage, ExampleGroup, ExampleGrid, ExampleCard, CompareTable } from '../components/kit';

/* ------------------------------------------------------------------ *
 * Color modes
 * ------------------------------------------------------------------ */

type ColorMode = 'blue' | 'green' | 'grey';

const MODES: { id: ColorMode; label: string; hint: string }[] = [
  { id: 'blue', label: '蓝主题', hint: '默认主题。' },
  { id: 'green', label: '绿主题', hint: '全局切换绿主题时，插画自动变绿。' },
  { id: 'grey', label: '灰稿', hint: '主题无关的灰稿，整图降至 80% 不透明度。' },
];

/** Mirrors :root in style.css — display-only pin for the blue tab (see header note). */
const BLUE_ILLUS_VARS = {
  '--illus-100': '190 218 255',
  '--illus-300': '106 161 255',
  '--illus-500': '22 93 255',
} as CSSProperties;

/* ------------------------------------------------------------------ *
 * Illustration inventory — everything exported from ~/components/illustrations
 * ------------------------------------------------------------------ */

/* KnowledgeSpaceIcon is deliberately NOT shown here: it's a themed icon with two
   bespoke drawings switched by the Recoil brand theme, not an --illus-* illustration. */
interface IllustrationDef {
  name: string;
  usage: string;
  Comp: ComponentType<{ className?: string; grey?: boolean }>;
}

const ILLUSTRATIONS: IllustrationDef[] = [
  {
    name: 'EmptyStateIllustration',
    usage: '通用空状态 — 列表 / 成员 / 频道等无数据',
    Comp: EmptyStateIllustration,
  },
  {
    name: 'NoPermissionIllustration',
    usage: '无权限访问 / 内容待审核不可见',
    Comp: NoPermissionIllustration,
  },
  {
    name: 'ListWebLinkIllustration',
    usage: '列表网页链接 — 按名称搜索无收录空态',
    Comp: ListWebLinkIllustration,
  },
  {
    name: 'CrawlingIllustration',
    usage: '爬取中 — 网页爬取等待态',
    Comp: CrawlingIllustration,
  },
  {
    name: 'SuccessIllustration',
    usage: '成功态 — 跟随品牌主题',
    Comp: SuccessIllustration,
  },
  {
    name: 'ArticleQAIllustration',
    usage: '文章问答场景',
    Comp: ArticleQAIllustration,
  },
  {
    name: 'SystemMaintenanceIllustration',
    usage: '系统维护 — 后端 500 全屏维护弹层',
    Comp: SystemMaintenanceIllustration,
  },
];

/* ------------------------------------------------------------------ *
 * Page
 * ------------------------------------------------------------------ */

export function IllustrationSection() {
  const [mode, setMode] = useState<ColorMode>('blue');
  const activeMode = MODES.find((m) => m.id === mode)!;

  return (
    <ComponentPage
      title="插画"
      eng="Illustration"
      description={
        <>
          空状态 / 状态反馈用的主题化插画，颜色走独立的插画调色板（比 UI 品牌色更亮），
          随蓝⇄绿主题自动切换，另有主题无关的灰稿模式。
        </>
      }
      whenToUse={[
        <>空状态 / 加载 / 无权限 / 成功等场景一律用这批插画组件，不再用静态 PNG。</>,
        <>灰稿：给组件传 <code>grey</code> 属性，主题无关、整图降 80% 不透明度。</>,
        <>插画调色板只给插画用；UI 图标仍走品牌色。</>,
      ]}
    >
      <ExampleGroup title="调色板三态">

        <CompareTable
          head={['档', '蓝主题（默认）', '绿主题', '灰稿']}
          rows={[
            ['浅底', <Swatch hex="#BEDAFF" key="b" />, <Swatch hex="#DDF0E8" key="g" />, <Swatch hex="#E5E5E5" key="y" />],
            ['中间调', <Swatch hex="#6AA1FF" key="b" />, <Swatch hex="#A2D7B5" key="g" />, <Swatch hex="#FFFFFF" key="y" />],
            ['主体', <Swatch hex="#165DFF" key="b" />, <Swatch hex="#169C47" key="g" />, <Swatch hex="#BCBCBC" key="y" />],
            ['整图不透明度', '100%', '100%', '80%'],
          ]}
        />
      </ExampleGroup>

      <ExampleGroup title="全部插画">
        {/* Local segmented control — same recipe as the gallery sidebar's mode switch:
            36px total = 1px border + 2px padding + 30px options; 2px gap; radius 8 outer / 6 inner. */}
        <div className="mb-2 inline-grid h-9 grid-cols-3 gap-0.5 rounded-lg border border-border-base p-0.5">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              className={cn(
                'h-[30px] rounded-md px-4 text-body-sm transition-colors',
                mode === m.id
                  ? 'bg-blue-500/[0.08] font-medium text-blue-500'
                  : 'text-muted-foreground hover:bg-muted/60',
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="mb-4 text-body-sm text-muted-foreground">{activeMode.hint}</p>

        <div
          className={mode === 'green' ? 'theme-green' : undefined}
          style={mode === 'blue' ? BLUE_ILLUS_VARS : undefined}
        >
          <ExampleGrid cols={4}>
            {ILLUSTRATIONS.map(({ name, usage, Comp }) => (
              <ExampleCard key={name} title={name} description={usage}>
                <div className="flex w-full justify-center">
                  <Comp className="size-[120px]" grey={mode === 'grey'} />
                </div>
              </ExampleCard>
            ))}
          </ExampleGrid>
        </div>
      </ExampleGroup>
    </ComponentPage>
  );
}

/** Inline swatch + hex label for the palette table (display-only spec values). */
function Swatch({ hex }: { hex: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className="inline-block h-6 w-10 shrink-0 rounded border border-black/10"
        style={{ background: hex }}
      />
      <code className="whitespace-nowrap text-caption text-muted-foreground">{hex}</code>
    </div>
  );
}
