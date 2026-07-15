/**
 * Gallery-only presentational helpers — antd-docs-style layout.
 *
 * DEV-ONLY internal tooling — this whole `_gallery` folder is never shipped to
 * production (the route is gated behind `import.meta.env.DEV`, see routes/index.tsx).
 * It exists so the UI designer can eyeball every component's states/variants in the
 * real app theme while unifying them. See docs-ui-refactor/00-总纲.md.
 *
 * Structure mirrors ant.design/components/*: each component is ONE page —
 *   ComponentPage(title + description + 何时使用/规则)
 *     └─ ExampleGroup(子标题)
 *          └─ ExampleGrid → ExampleCard(演示区 + 分隔线 + 说明)
 */
import { ReactNode } from 'react';
import { cn } from '~/utils';

/* ------------------------------------------------------------------ *
 * Page shell — the antd component-doc page skeleton.
 * ------------------------------------------------------------------ */

export function ComponentPage({
  title,
  eng,
  description,
  whenToUse,
  children,
}: {
  title: string;
  eng?: string;
  description?: ReactNode;
  /** 何时使用 / 使用规则 — rendered as a bordered bullet list, antd-style. */
  whenToUse?: ReactNode[];
  children: ReactNode;
}) {
  return (
    <article className="mx-auto max-w-4xl px-8 py-10">
      <header className="mb-8">
        <h1 className="flex items-baseline gap-3 text-h1 text-text-primary">
          {title}
          {eng && <span className="text-h4 font-normal text-muted-foreground">{eng}</span>}
        </h1>
        {description && (
          <p className="mt-3 max-w-3xl text-body text-text-primary">{description}</p>
        )}
      </header>

      {whenToUse && whenToUse.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-3 text-h3 text-text-primary">何时使用 / 规则</h2>
          <ul className="space-y-2 rounded-xl border border-border-light bg-muted/20 p-5">
            {whenToUse.map((item, i) => (
              <li key={i} className="flex gap-2 text-body text-text-primary">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-blue-500" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-4 text-h3 text-text-primary">代码演示 / 状态</h2>
        {children}
      </section>
    </article>
  );
}

/* ------------------------------------------------------------------ *
 * Example group — a titled cluster of examples within a page.
 * ------------------------------------------------------------------ */

export function ExampleGroup({
  title,
  subtitle,
  children,
}: {
  title?: string;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mb-8">
      {title && <h3 className="mb-1 text-h4 text-text-primary">{title}</h3>}
      {subtitle && <p className="mb-3 text-body-sm text-muted-foreground">{subtitle}</p>}
      {!subtitle && title && <div className="mb-3" />}
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Example card — antd demo cell: live demo on top, meta below a divider.
 * ------------------------------------------------------------------ */

export function ExampleCard({
  title,
  description,
  className,
  children,
}: {
  title: string;
  description?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn('overflow-hidden rounded-xl border border-border-light bg-background', className)}>
      <div className="flex min-h-[88px] flex-wrap items-center gap-3 p-6">{children}</div>
      <div className="border-t border-dashed border-border-light px-5 py-3">
        <div className="text-body-sm font-medium text-text-primary">{title}</div>
        {description && <div className="mt-0.5 text-caption text-muted-foreground">{description}</div>}
      </div>
    </div>
  );
}

/** Responsive grid for laying out ExampleCard / Demo cells. */
export function ExampleGrid({ children, cols = 3 }: { children: ReactNode; cols?: 1 | 2 | 3 | 4 }) {
  const colClass =
    cols === 1
      ? ''
      : cols === 2
        ? 'sm:grid-cols-2'
        : cols === 4
          ? 'sm:grid-cols-2 lg:grid-cols-4'
          : 'sm:grid-cols-2 lg:grid-cols-3';
  return <div className={cn('grid grid-cols-1 gap-4', colClass)}>{children}</div>;
}

/* ------------------------------------------------------------------ *
 * A small comparison table for documenting differences between variants.
 * ------------------------------------------------------------------ */

export function CompareTable({
  head,
  rows,
}: {
  head: string[];
  rows: (string | ReactNode)[][];
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border-light">
      <table className="w-full text-left text-body-sm">
        <thead className="bg-muted/40">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-4 py-2.5 font-medium text-text-primary">
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

/* ------------------------------------------------------------------ *
 * Legacy aliases — Demo / DemoGrid are still used by migrated pages
 * (they now forward to ExampleCard / ExampleGrid). Section is unused by
 * gallery pages (all migrated to ComponentPage) but kept as a safety net.
 * ------------------------------------------------------------------ */

/** @deprecated use ExampleGroup inside a ComponentPage. */
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
    <section id={id} className="mx-auto max-w-4xl px-8 py-10">
      <div className="mb-6">
        <h1 className="text-h1 text-text-primary">{title}</h1>
        {subtitle && <p className="mt-3 max-w-3xl text-body text-text-primary">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

/** @deprecated use ExampleCard. */
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
  return <ExampleCard title={label} description={note} className={className}>{children}</ExampleCard>;
}

/** @deprecated use ExampleGrid. */
export function DemoGrid({ children, cols = 3 }: { children: ReactNode; cols?: 1 | 2 | 3 | 4 }) {
  return <ExampleGrid cols={cols}>{children}</ExampleGrid>;
}
