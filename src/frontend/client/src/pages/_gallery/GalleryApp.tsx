/**
 * Component Gallery — DEV-ONLY internal tooling for the UI unification effort.
 *
 * NOT shipped to production: the `/gallery` route is registered only when
 * `import.meta.env.DEV` is true (see src/routes/index.tsx), so this whole tree is
 * tree-shaken out of the production build. Changing a component shown here changes the
 * real shared component, so every business page updates too.
 *
 * Default export (required by React.lazy in the route). See docs-ui-refactor/00-总纲.md.
 */
import { useState } from 'react';
import { cn } from '~/utils';
import { OverviewSection } from './sections/OverviewSection';
import { ModalSection } from './sections/ModalSection';
import { ButtonSection } from './sections/ButtonSection';

interface NavItem {
  id: string;
  label: string;
  status?: 'wip' | 'todo' | 'done';
}

const NAV: NavItem[] = [
  { id: 'overview', label: '总览' },
  { id: 'modal', label: 'Modal 弹窗', status: 'wip' },
  { id: 'button', label: 'Button 按钮', status: 'todo' },
];

const STATUS_DOT: Record<NonNullable<NavItem['status']>, string> = {
  wip: 'bg-amber-500',
  todo: 'bg-gray-300',
  done: 'bg-green-500',
};

export default function GalleryApp() {
  const [active, setActive] = useState('overview');

  const handleNav = (id: string) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-border-light bg-muted/20">
        <div className="border-b border-border-light px-5 py-4">
          <div className="text-base font-semibold text-text-primary">组件画廊</div>
          <div className="mt-0.5 text-xs text-muted-foreground">DEV only · 不会发版</div>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {NAV.map((item) => (
            <button
              key={item.id}
              onClick={() => handleNav(item.id)}
              className={cn(
                'flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors',
                active === item.id
                  ? 'bg-blue-500/[0.08] font-medium text-text-primary'
                  : 'text-muted-foreground hover:bg-muted/60',
              )}
            >
              {item.status && (
                <span className={cn('size-1.5 rounded-full', STATUS_DOT[item.status])} />
              )}
              {item.label}
            </button>
          ))}
        </nav>
        <div className="border-t border-border-light px-5 py-3 text-xs text-muted-foreground">
          文档：docs-ui-refactor/
        </div>
      </aside>

      {/* Content */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl px-8 py-8">
          <OverviewSection />
          <ModalSection />
          <ButtonSection />
        </div>
      </main>
    </div>
  );
}
