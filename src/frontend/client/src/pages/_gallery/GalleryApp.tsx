/**
 * Component Gallery — DEV-ONLY internal tooling for the UI unification effort.
 *
 * NOT shipped to production: the `/gallery` route is registered only when
 * `import.meta.env.DEV` is true (see src/routes/index.tsx), so this whole tree is
 * tree-shaken out of the production build. Changing a component shown here changes the
 * real shared component, so every business page updates too.
 *
 * Layout mirrors ant.design/components: left sidebar navigates between component
 * pages; the main area shows ONE component page at a time (not a long scroll).
 * Default export (required by React.lazy in the route). See docs-ui-refactor/00-总纲.md.
 */
import { ComponentType, useState } from 'react';
import { cn } from '~/utils';
import { OverviewSection } from './sections/OverviewSection';
import { ResponsiveSection } from './sections/ResponsiveSection';
import { TypographySection } from './sections/TypographySection';
import { ModalSection } from './sections/ModalSection';
import { ConfirmDialogSection } from './sections/ConfirmDialogSection';
import { ButtonSection } from './sections/ButtonSection';
import { FeedbackSection } from './sections/FeedbackSection';

type Status = 'wip' | 'todo' | 'done';

interface PageDef {
  id: string;
  label: string;
  group: string;
  status?: Status;
  Page: ComponentType;
}

/** Registry — one entry per component page. Grouped like antd's sidebar. */
const PAGES: PageDef[] = [
  { id: 'overview', label: '总览', group: '开始', Page: OverviewSection },
  { id: 'responsive', label: '多端适配 Responsive', group: '开始', Page: ResponsiveSection },
  { id: 'typography', label: '字体 Typography', group: '基础 Foundation', status: 'wip', Page: TypographySection },
  { id: 'button', label: 'Button 按钮', group: '通用 General', status: 'todo', Page: ButtonSection },
  { id: 'modal', label: 'Modal 弹窗', group: '反馈 Feedback', status: 'wip', Page: ModalSection },
  { id: 'confirm', label: '二次确认弹窗', group: '反馈 Feedback', status: 'wip', Page: ConfirmDialogSection },
  { id: 'feedback', label: '点赞 / 点踩', group: '反馈 Feedback', status: 'done', Page: FeedbackSection },
];

const STATUS_DOT: Record<Status, string> = {
  wip: 'bg-amber-500',
  todo: 'bg-gray-300',
  done: 'bg-green-500',
};

/** Preserve group order as declared in PAGES. */
const GROUPS = PAGES.reduce<string[]>((acc, p) => {
  if (!acc.includes(p.group)) acc.push(p.group);
  return acc;
}, []);

export default function GalleryApp() {
  const [activeId, setActiveId] = useState('overview');
  const active = PAGES.find((p) => p.id === activeId) ?? PAGES[0];
  const ActivePage = active.Page;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* Sidebar */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-border-light bg-muted/20">
        <div className="border-b border-border-light px-5 py-4">
          <div className="text-h4 text-text-primary">组件画廊</div>
          <div className="mt-0.5 text-caption text-muted-foreground">DEV only · 不会发版</div>
        </div>
        <nav className="flex-1 overflow-y-auto p-3">
          {GROUPS.map((group) => (
            <div key={group} className="mb-4">
              <div className="px-3 pb-1 text-caption font-medium uppercase tracking-wide text-muted-foreground">
                {group}
              </div>
              {PAGES.filter((p) => p.group === group).map((p) => (
                <button
                  key={p.id}
                  onClick={() => setActiveId(p.id)}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-body transition-colors',
                    activeId === p.id
                      ? 'bg-blue-500/[0.08] font-medium text-text-primary'
                      : 'text-muted-foreground hover:bg-muted/60',
                  )}
                >
                  {p.status && <span className={cn('size-1.5 rounded-full', STATUS_DOT[p.status])} />}
                  <span className="truncate">{p.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-border-light px-5 py-3 text-caption text-muted-foreground">
          文档：docs-ui-refactor/
        </div>
      </aside>

      {/* Content — one component page at a time */}
      <main key={activeId} className="flex-1 overflow-y-auto">
        <ActivePage />
      </main>
    </div>
  );
}
