import { Tag, Tooltip } from '@bisheng/ui';
import cn from '@bisheng/ui/cn';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { versionDialogStyles as styles } from './versionDialogStyles';

interface VersionHistorySummaryProps {
  documentTitle?: string | null;
  documentCode?: string | null;
  primaryVersion?: number | null;
}

export function VersionHistorySummary({ documentTitle, documentCode, primaryVersion }: VersionHistorySummaryProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version.history' });
  const fields = [
    { label: t('document'), value: documentTitle },
    { label: t('document_code'), value: documentCode },
    { label: t('current_primary'), value: primaryVersion == null ? null : `V${primaryVersion}` },
  ];
  return (
    <dl className={`mb-4 grid grid-cols-3 gap-3 sm:gap-6 ${styles.summary}`}>
      {fields.map(({ label, value }) => (
        <div key={label} className="min-w-0">
          <dt className={`mb-1 ${styles.fieldLabel}`}>{label}</dt>
          <dd className={`truncate ${styles.summaryValue}`} title={value ?? undefined}>{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

interface VersionHistoryActionProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: 'primary' | 'danger';
  children: ReactNode;
}

export function VersionHistoryAction({ label, onClick, disabled, tone, children }: VersionHistoryActionProps) {
  return (
    <Tooltip content={label} side="top">
      <button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
        className={cn(styles.historyAction, tone === 'primary' && 'text-blue-500 hover:text-blue-500', tone === 'danger' && 'hover:text-danger')}
      >
        {children}
      </button>
    </Tooltip>
  );
}

const progressBadge = 'bg-blue-50 text-blue-500';
const dangerBadge = 'bg-danger-tint text-danger';
const statusBadgeStyles = {
  1: { label: 'parsing', className: progressBadge },
  2: { label: 'success', className: 'bg-success-tint text-success' },
  3: { label: 'failed', className: dangerBadge },
  4: { label: 'processing', className: progressBadge },
  5: { label: 'queueing', className: progressBadge },
  6: { label: 'timeout', className: dangerBadge },
  7: { label: 'violation', className: dangerBadge },
} as const;

interface VersionHistoryStatusBadgeProps {
  status: number;
}

export function VersionHistoryStatusBadge({ status }: VersionHistoryStatusBadgeProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version.history' });
  const badge = statusBadgeStyles[status as keyof typeof statusBadgeStyles] ?? statusBadgeStyles[5];
  const label = t(`status.${badge.label}`);
  return (
    <span title={label} className={`inline-block max-w-full truncate rounded px-2 py-0.5 align-middle text-xs ${badge.className}`}>
      {label}
    </span>
  );
}

export interface VersionHistoryTableRow {
  id: number;
  versionNumber: number;
  isPrimary: boolean;
  fileName: string;
  fileCode?: string | null;
  uploader?: string | null;
  uploadedAt?: string | null;
  status: ReactNode;
  actions: ReactNode;
}

interface VersionHistoryTableProps {
  rows: readonly VersionHistoryTableRow[];
  compact?: boolean;
}

const columns = [
  { label: 'version', width: 'w-[100px]', padding: 'px-4' },
  { label: 'filename', width: undefined, padding: 'px-4' },
  { label: 'file_code', width: 'w-[68px]', padding: 'px-2' },
  { label: 'uploader', width: 'w-[72px]', padding: 'px-3' },
  { label: 'upload_time', width: 'w-[146px]', padding: 'px-4' },
  { label: 'parse_status', width: 'w-[84px]', padding: 'px-3' },
  { label: 'actions', width: 'w-[162px]', padding: 'px-4' },
] as const;

export function VersionHistoryTable({ rows, compact = false }: VersionHistoryTableProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version.history' });
  if (compact) {
    return (
      <ol className="divide-y divide-border-base border-t border-border-base">
        {rows.map(row => (
          <li key={row.id} className="space-y-3 py-4 last:pb-0">
            <div className="flex flex-wrap items-center gap-2 text-sm text-text-1">
              <span className="font-medium">V{row.versionNumber}</span>
              {row.isPrimary && <Tag size="small" color="brand">{t('primary_badge')}</Tag>}
              {row.status}
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm [overflow-wrap:anywhere]">
              <div className="col-span-2 min-w-0">
                <dt className={styles.fieldLabel}>{t('columns.filename')}</dt>
                <dd>{row.fileName}</dd>
              </div>
              {[
                { label: 'file_code', value: row.fileCode },
                { label: 'uploader', value: row.uploader },
                { label: 'upload_time', value: row.uploadedAt?.replace('T', ' ') },
              ].map(({ label, value }) => (
                <div key={label} className="min-w-0">
                  <dt className={styles.fieldLabel}>{t(`columns.${label}`)}</dt>
                  <dd>{value || '—'}</dd>
                </div>
              ))}
            </dl>
            <div className="flex flex-wrap items-center gap-2">{row.actions}</div>
          </li>
        ))}
      </ol>
    );
  }
  return (
    <div className={`overflow-x-auto ${styles.historyList}`}>
      <table className="w-full min-w-[760px] table-fixed border-collapse text-sm">
        <colgroup>
          {columns.map(column => <col key={column.label} className={column.width} />)}
        </colgroup>
        <thead>
          <tr className="border-b border-border-base bg-fill-1">
            {columns.map(column => (
              <th key={column.label} scope="col" className={`break-words py-2.5 text-left text-xs font-medium text-text-3 ${column.padding}`}>
                {t(`columns.${column.label}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const uploadTime = row.uploadedAt?.replace('T', ' ');
            return (
              <tr key={row.id} className={styles.historyRow}>
                <td className="whitespace-nowrap px-4 py-3 text-text-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">V{row.versionNumber}</span>
                    {row.isPrimary && (
                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-500">
                        {t('primary_badge')}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-text-1">
                  <span className="block truncate" title={row.fileName}>{row.fileName}</span>
                </td>
                <td className="px-2 py-3 text-text-2">
                  <span className="block truncate" title={row.fileCode ?? undefined}>{row.fileCode ?? '—'}</span>
                </td>
                <td className="px-3 py-3 text-text-2">
                  <span className="block truncate" title={row.uploader ?? undefined}>{row.uploader ?? '—'}</span>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-text-2" title={uploadTime}>{uploadTime?.slice(0, 16) || '—'}</td>
                <td className="px-3 py-3 text-text-2 [&>span]:max-w-full">{row.status ?? '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex min-h-7 items-center gap-1.5">{row.actions}</div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
