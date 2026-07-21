/**
 * Component Gallery — DEV-ONLY internal tooling for the UI unification effort.
 *
 * NOT shipped to production: the `/gallery` route is registered only when
 * `import.meta.env.DEV` is true (see src/routes/index.tsx), so this whole tree is
 * tree-shaken out of the production build. Changing a component shown here changes the
 * real shared component, so every business page updates too.
 *
 * Two audience-facing modes, switched by the segmented control in the sidebar:
 *   规范 (spec)     — how to USE the design system today; for designers/engineers/PMs.
 *                     sections/*  (antd-docs-style pages, no migration noise)
 *   进度 (progress) — migration dashboards & ledgers for the effort's owner.
 *                     progress/*  (status dots live here only)
 * Default export (required by React.lazy in the route). See docs-ui-refactor/00-总纲.md.
 */
import { ComponentType, useState } from 'react';
import { cn } from '~/utils';
import { OverviewSection } from './sections/OverviewSection';
import { ResponsiveSection } from './sections/ResponsiveSection';
import { TypographySection } from './sections/TypographySection';
import { ColorSection } from './sections/ColorSection';
import { IllustrationSection } from './sections/IllustrationSection';
import { ModalSection } from './sections/ModalSection';
import { ConfirmDialogSection } from './sections/ConfirmDialogSection';
import { ButtonSection } from './sections/ButtonSection';
import { FeedbackSection } from './sections/FeedbackSection';
import { ProgressOverview } from './progress/ProgressOverview';
import { TypographyProgress } from './progress/TypographyProgress';
import { ColorProgress } from './progress/ColorProgress';
import { ButtonProgress } from './progress/ButtonProgress';
import { ModalProgress } from './progress/ModalProgress';
import { ConfirmProgress } from './progress/ConfirmProgress';

type Mode = 'spec' | 'progress';
type Status = 'wip' | 'todo' | 'done';

interface PageDef {
  id: string;
  label: string;
  group: string;
  /** Migration status — progress mode only (spec readers don't care). */
  status?: Status;
  /** Spec not finalized yet — shows a 未定稿 tag in spec mode. */
  draft?: boolean;
  Page: ComponentType;
}

/** Spec registry — the design system as consumers should use it today. */
const SPEC_PAGES: PageDef[] = [
  { id: 'overview', label: '总览', group: '总则', Page: OverviewSection },
  { id: 'responsive', label: '多端适配 Responsive', group: '总则', Page: ResponsiveSection },
  { id: 'typography', label: '字体 Typography', group: '基础 Foundation', Page: TypographySection },
  { id: 'color', label: '色彩 Colors', group: '基础 Foundation', Page: ColorSection },
  { id: 'illustration', label: '插画 Illustration', group: '基础 Foundation', Page: IllustrationSection },
  { id: 'button', label: 'Button 按钮', group: '通用 General', Page: ButtonSection },
  { id: 'modal', label: 'Modal 弹窗', group: '反馈 Feedback', draft: true, Page: ModalSection },
  { id: 'confirm', label: '二次确认弹窗', group: '反馈 Feedback', Page: ConfirmDialogSection },
  { id: 'feedback', label: '点赞 / 点踩', group: '反馈 Feedback', Page: FeedbackSection },
];

/** Progress registry — migration dashboards & ledgers, one per in-flight component. */
const PROGRESS_PAGES: PageDef[] = [
  { id: 'overview', label: '现状总览', group: '总则', Page: ProgressOverview },
  { id: 'typography', label: '字体 Typography', group: '基础 Foundation', status: 'wip', Page: TypographyProgress },
  { id: 'color', label: '色彩 Colors', group: '基础 Foundation', status: 'wip', Page: ColorProgress },
  { id: 'button', label: 'Button 按钮', group: '通用 General', status: 'wip', Page: ButtonProgress },
  { id: 'modal', label: 'Modal 弹窗', group: '反馈 Feedback', status: 'wip', Page: ModalProgress },
  { id: 'confirm', label: '二次确认弹窗', group: '反馈 Feedback', status: 'wip', Page: ConfirmProgress },
];

/* Order matters — Object.keys drives the segment control, and 现状梳理 is the
   gallery's primary job (the written spec now lives in the separate rspress site). */
const REGISTRY: Record<Mode, PageDef[]> = { progress: PROGRESS_PAGES, spec: SPEC_PAGES };

const MODE_LABEL: Record<Mode, string> = { progress: '现状梳理', spec: '设计规范' };

const STATUS_DOT: Record<Status, string> = {
  wip: 'bg-amber-500',
  todo: 'bg-gray-300',
  done: 'bg-green-500',
};

/** Preserve group order as declared in the registry. */
function groupsOf(pages: PageDef[]): string[] {
  return pages.reduce<string[]>((acc, p) => {
    if (!acc.includes(p.group)) acc.push(p.group);
    return acc;
  }, []);
}

export default function GalleryApp() {
  const [mode, setMode] = useState<Mode>('progress');
  /* Remember the active page per mode, so toggling back restores where you were. */
  const [activeIds, setActiveIds] = useState<Record<Mode, string>>({
    spec: 'overview',
    progress: 'overview',
  });

  const pages = REGISTRY[mode];
  const active = pages.find((p) => p.id === activeIds[mode]) ?? pages[0];
  const ActivePage = active.Page;

  const handleSwitchMode = (next: Mode) => {
    if (next === mode) return;
    /* Keep the same component page across modes when it exists on both sides. */
    setActiveIds((ids) => ({
      ...ids,
      [next]: REGISTRY[next].some((p) => p.id === active.id) ? active.id : 'overview',
    }));
    setMode(next);
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* Sidebar */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-border-light bg-muted/20">
        <div className="border-b border-border-light px-5 py-4">
          <div className="text-h4 text-text-primary">组件画廊</div>
          <div className="mt-0.5 text-caption text-muted-foreground">DEV only</div>
        </div>

        {/* Mode segmented control — spec for consumers, progress for the owner */}
        <div className="p-3">
          {/* 36px total = 1px border + 2px padding + 30px options; 2px gap; radius 8 outer / 6 inner */}
          <div className="grid h-9 grid-cols-2 gap-0.5 rounded-lg border border-border-base p-0.5">
            {(Object.keys(REGISTRY) as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => handleSwitchMode(m)}
                className={cn(
                  'h-[30px] rounded-md px-2 text-body-sm transition-colors',
                  mode === m
                    ? 'bg-blue-500/[0.08] font-medium text-blue-500'
                    : 'text-muted-foreground hover:bg-muted/60',
                )}
              >
                {MODE_LABEL[m]}
              </button>
            ))}
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto p-3">
          {groupsOf(pages).map((group) => (
            <div key={group} className="mb-4">
              {/* antd-style 3-level hierarchy: group lightest, items darkest, active = brand */}
              <div className="px-3 pb-1.5 text-caption text-text-3">{group}</div>
              {pages
                .filter((p) => p.group === group)
                .map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setActiveIds((ids) => ({ ...ids, [mode]: p.id }))}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-lg py-2 pl-5 pr-3 text-left text-body transition-colors',
                      active.id === p.id
                        ? 'bg-blue-500/[0.08] font-medium text-blue-500'
                        : 'text-text-1 hover:bg-muted/60',
                    )}
                  >
                    {mode === 'progress' && p.status && (
                      <span className={cn('size-1.5 rounded-full', STATUS_DOT[p.status])} />
                    )}
                    <span className="truncate">{p.label}</span>
                    {mode === 'spec' && p.draft && (
                      <span className="ml-auto shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-caption text-amber-600">
                        未定稿
                      </span>
                    )}
                  </button>
                ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-border-light px-5 py-3 text-caption text-muted-foreground">
          文档：docs-ui-refactor/
        </div>
      </aside>

      {/* Content — one page at a time */}
      <main key={`${mode}-${active.id}`} className="flex-1 overflow-y-auto">
        <ActivePage />
      </main>
    </div>
  );
}
