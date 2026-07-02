/**
 * Gallery-only presentational helpers.
 *
 * DEV-ONLY internal tooling — this whole `_gallery` folder is never shipped to
 * production (the route is gated behind `import.meta.env.DEV`, see routes/index.tsx).
 * It exists so the UI designer can eyeball every component's states/variants in the
 * real app theme while unifying them. See docs-ui-refactor/00-总纲.md.
 */
import { ReactNode } from 'react';
import { cn } from '~/utils';

/** A titled block that groups one component's examples. */
export function Section({
  id,
  title,
  subtitle,
  children,
}: {
  id?: string;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} className="mb-16 scroll-mt-6">
      <div className="mb-4 border-b border-border-light pb-3">
        <h2 className="text-xl font-semibold text-text-primary">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

/** A labeled example cell — shows one variant/state with a caption underneath. */
export function Demo({
  label,
  note,
  className,
  children,
}: {
  label: string;
  note?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        'flex flex-col gap-3 rounded-xl border border-border-light bg-background p-5',
        className,
      )}
    >
      <div className="flex min-h-[64px] flex-wrap items-center gap-3">{children}</div>
      <div className="mt-auto">
        <div className="text-sm font-medium text-text-primary">{label}</div>
        {note && <div className="mt-0.5 text-xs text-muted-foreground">{note}</div>}
      </div>
    </div>
  );
}

/** Responsive grid for laying out Demo cells. */
export function DemoGrid({ children, cols = 3 }: { children: ReactNode; cols?: 2 | 3 | 4 }) {
  const colClass =
    cols === 2
      ? 'sm:grid-cols-2'
      : cols === 4
        ? 'sm:grid-cols-2 lg:grid-cols-4'
        : 'sm:grid-cols-2 lg:grid-cols-3';
  return <div className={cn('grid grid-cols-1 gap-4', colClass)}>{children}</div>;
}

/** A small comparison table for documenting differences between variants. */
export function CompareTable({
  head,
  rows,
}: {
  head: string[];
  rows: (string | ReactNode)[][];
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border-light">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/40">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="px-4 py-2.5 font-medium text-text-primary">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="border-t border-border-light">
              {row.map((cell, ci) => (
                <td key={ci} className="px-4 py-2.5 text-muted-foreground">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
