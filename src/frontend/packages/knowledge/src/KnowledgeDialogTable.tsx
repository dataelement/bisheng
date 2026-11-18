import type { ReactNode } from 'react';

interface KnowledgeDialogTableProps {
  caption: string;
  showCaption?: boolean;
  columns: readonly { label: string; numeric?: boolean; breakLongWords?: boolean }[];
  rows: readonly { key: string | number; cells: readonly ReactNode[] }[];
}

export function KnowledgeDialogTable({
  caption,
  showCaption = true,
  columns,
  rows,
}: KnowledgeDialogTableProps) {
  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="w-full text-body-sm text-text-1">
        <caption className={showCaption ? 'pb-2 text-left font-medium' : 'sr-only'}>
          {caption}
        </caption>
        <thead className="bg-fill-1">
          <tr>
            {columns.map(({ label, numeric }) => (
              <th
                key={label}
                scope="col"
                className={`h-10 px-1.5 py-1.5 font-medium sm:px-3 ${numeric ? 'text-right' : 'text-left'}`}
              >
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
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
