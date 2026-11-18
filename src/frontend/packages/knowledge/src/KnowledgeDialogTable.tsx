import type { ReactNode } from 'react';

interface KnowledgeDialogTableProps {
  caption: string;
  showCaption?: boolean;
  scrollable?: boolean;
  emptyContent?: ReactNode;
  columns: readonly { label: string; header?: ReactNode; numeric?: boolean; breakLongWords?: boolean }[];
  rows: readonly { key: string | number; cells: readonly ReactNode[] }[];
}

export function KnowledgeDialogTable({
  caption,
  showCaption = true,
  scrollable = false,
  emptyContent,
  columns,
  rows,
}: KnowledgeDialogTableProps) {
  return (
    <div className={scrollable ? 'min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain' : 'min-w-0 overflow-x-auto'}>
      <table className="w-full text-body-sm text-text-1">
        <caption className={showCaption ? 'pb-2 text-left font-medium' : 'sr-only'}>
          {caption}
        </caption>
        <thead className={scrollable ? 'sticky top-0 z-10 bg-fill-1' : 'bg-fill-1'}>
          <tr>
            {columns.map(({ label, header, numeric }) => (
              <th
                key={label}
                scope="col"
                className={`h-10 px-1.5 py-1.5 font-medium sm:px-3 ${numeric ? 'text-right' : 'text-left'}`}
              >
                {header ?? label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {!rows.length && emptyContent && (
            <tr>
              <td colSpan={columns.length}>{emptyContent}</td>
            </tr>
          )}
          {rows.map(({ key, cells }) => (
            <tr key={key} className="even:bg-fill-1/60 [overflow-wrap:anywhere]">
              {cells.map((cell, index) =>
                index === 0 ? (
                  <th
                    key={index}
                    scope="row"
                    className={`h-10 px-1.5 py-1.5 text-left font-normal sm:px-3 ${columns[0]?.breakLongWords === false ? 'break-normal' : ''}`}
                  >
                    {cell}
                  </th>
                ) : (
                  <td
                    key={index}
                    className={`h-10 px-1.5 py-1.5 sm:px-3 ${columns[index]?.numeric ? 'whitespace-nowrap text-right tabular-nums' : ''} ${columns[index]?.breakLongWords === false ? 'break-normal' : ''}`}
                  >
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
