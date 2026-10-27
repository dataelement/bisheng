import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * One presentation of a hosted application's version diff, used by **both**
 * apps (F055 AC-41: "版本 tab 与审读视图同一呈现").
 *
 * It lives here rather than in either app because "the same presentation" has
 * to be the same *component* — the platform's version tab and the client's
 * review view are in two SPAs that share no `src/`, and two copies of a diff
 * renderer diverge on the first bug fix. The package is the only cross-app
 * source-shipped place both already depend on, and its contract fits: props
 * in, no HTTP client, copy from the shared i18n namespace.
 *
 * Everything shown is computed server-side (`version_diff_service`): the
 * archives never reach the browser, the patch text is already masked, and the
 * three size caps have already been applied. This component adds no logic of
 * its own beyond folding the unified-diff text into coloured lines.
 *
 * Classes stay inside Tailwind's default palette on purpose. The two apps do
 * not share a theme layer — the client has the design-token preset, the
 * platform does not — so a `text-text-1` here would render as nothing in one
 * of them.
 */

export type VersionDiffChange = 'added' | 'removed' | 'modified';

/** One changed file. `comparable: false` means binary or over-sized: listed, never diffed. */
export interface VersionDiffFile {
  path: string;
  change: VersionDiffChange | string;
  additions: number;
  deletions: number;
  comparable: boolean;
  reason: string | null;
}

/** The unified-diff text of one comparable file. `patch: null` = the total-size cap was hit. */
export interface VersionDiffPatch {
  path: string;
  change: VersionDiffChange | string;
  patch: string | null;
  truncated: boolean;
  masked_secrets: number;
}

export interface VersionDiffSummary {
  files_changed: number;
  additions: number;
  deletions: number;
  truncated: boolean;
}

export interface VersionDiffViewProps {
  summary: VersionDiffSummary | null;
  files: VersionDiffFile[];
  patches: VersionDiffPatch[];
  /** Which two versions are being compared, rendered above the list. */
  caption?: React.ReactNode;
  loading?: boolean;
  /** Rendered instead of the list — a business-code message, already translated. */
  errorMessage?: string;
  /** Rendered instead of the list when there is nothing to compare against (a first release). */
  emptyMessage?: string;
  className?: string;
}

// `as const` rather than `Record<string, string>`: the client augments
// i18next's types from its resource files, so a `t()` argument widened to
// `string` fails that app's strict typecheck while passing this package's own.
const CHANGE_LABEL_KEY = {
  added: 'changeAdded',
  removed: 'changeRemoved',
  modified: 'changeModified',
} as const;

type ChangeLabelKey = (typeof CHANGE_LABEL_KEY)[keyof typeof CHANGE_LABEL_KEY];

function changeLabelKey(change: string): ChangeLabelKey {
  return CHANGE_LABEL_KEY[change as VersionDiffChange] ?? 'changeModified';
}

const CHANGE_MARK: Record<string, string> = {
  added: 'A',
  removed: 'D',
  modified: 'M',
};

const CHANGE_MARK_CLASS: Record<string, string> = {
  added: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  removed: 'bg-rose-50 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  modified: 'bg-amber-50 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
};

/** `previewable`/`comparable` reasons the scanner can answer with. */
const REASON_KEY = {
  binary: 'reasonBinary',
  too_large: 'reasonTooLarge',
} as const;

function reasonKey(reason: string | null): (typeof REASON_KEY)[keyof typeof REASON_KEY] | 'notComparable' {
  return REASON_KEY[(reason ?? '') as keyof typeof REASON_KEY] ?? 'notComparable';
}

type DiffLineKind = 'add' | 'del' | 'hunk' | 'meta' | 'context';

const LINE_CLASS: Record<DiffLineKind, string> = {
  add: 'bg-emerald-50 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200',
  del: 'bg-rose-50 text-rose-800 dark:bg-rose-900/30 dark:text-rose-200',
  hunk: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
  meta: 'text-slate-400 dark:text-slate-500',
  context: 'text-slate-700 dark:text-slate-300',
};

/** Classify one unified-diff line. `+++`/`---` are headers, not additions/deletions. */
export function classifyDiffLine(line: string): DiffLineKind {
  if (line.startsWith('+++') || line.startsWith('---')) return 'meta';
  if (line.startsWith('@@')) return 'hunk';
  if (line.startsWith('+')) return 'add';
  if (line.startsWith('-')) return 'del';
  return 'context';
}

function DiffBody({ patch }: { patch: string }) {
  const lines = useMemo(() => patch.replace(/\n$/, '').split('\n'), [patch]);
  return (
    <pre className="overflow-x-auto px-0 py-1 font-mono text-xs leading-5">
      {lines.map((line, index) => (
        <div key={index} className={`whitespace-pre px-3 ${LINE_CLASS[classifyDiffLine(line)]}`}>
          {line === '' ? ' ' : line}
        </div>
      ))}
    </pre>
  );
}

export function VersionDiffView({
  summary,
  files,
  patches,
  caption,
  loading = false,
  errorMessage,
  emptyMessage,
  className,
}: VersionDiffViewProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'hostedApp.versionDiff' });
  const [picked, setPicked] = useState<string | null>(null);

  const patchByPath = useMemo(() => {
    const index = new Map<string, VersionDiffPatch>();
    for (const patch of patches) index.set(patch.path, patch);
    return index;
  }, [patches]);

  // Follow the data, not the click: a re-fetch (other version picked, list
  // reloaded) must not leave the right pane on a path that is no longer in the
  // list, which renders as a blank panel with no explanation.
  //
  // Derived during render rather than reconciled in an effect: an effect would
  // paint one frame of the `selectFile` placeholder every time a diff arrives —
  // the list is on screen while the effect has yet to run — and that frame is
  // what a test asserting "the first file's patch is visible" catches
  // intermittently.
  const selected =
    picked && files.some((file) => file.path === picked) ? picked : (files[0]?.path ?? null);

  if (loading) {
    return <p className={`text-sm text-slate-500 dark:text-slate-400 ${className ?? ''}`}>{t('loading')}</p>;
  }
  if (errorMessage) {
    return <p className={`text-sm text-slate-500 dark:text-slate-400 ${className ?? ''}`}>{errorMessage}</p>;
  }
  if (emptyMessage) {
    return <p className={`text-sm text-slate-500 dark:text-slate-400 ${className ?? ''}`}>{emptyMessage}</p>;
  }

  const selectedFile = files.find((file) => file.path === selected) ?? null;
  const selectedPatch = selected ? (patchByPath.get(selected) ?? null) : null;

  return (
    <div className={`flex min-h-0 flex-col gap-3 ${className ?? ''}`} data-testid="version-diff-view">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        {caption ? <span className="text-slate-700 dark:text-slate-200">{caption}</span> : null}
        <span>{t('filesChanged', { count: summary?.files_changed ?? files.length })}</span>
        <span className="text-emerald-600 dark:text-emerald-400">
          {t('additions', { count: summary?.additions ?? 0 })}
        </span>
        <span className="text-rose-600 dark:text-rose-400">
          {t('deletions', { count: summary?.deletions ?? 0 })}
        </span>
        {summary?.truncated ? <span className="text-amber-600 dark:text-amber-400">{t('listTruncated')}</span> : null}
      </div>

      {files.length === 0 ? (
        <p className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-400">
          {t('identical')}
        </p>
      ) : (
        <div className="flex min-h-0 flex-col gap-3 md:flex-row">
          <ul className="max-h-64 shrink-0 overflow-y-auto rounded-md border border-slate-200 dark:border-slate-700 md:max-h-none md:w-72">
            {files.map((file) => {
              const active = file.path === selected;
              return (
                <li key={file.path}>
                  <button
                    type="button"
                    onClick={() => setPicked(file.path)}
                    aria-current={active}
                    className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs ${
                      active ? 'bg-slate-100 dark:bg-slate-800' : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
                    }`}
                  >
                    <span
                      title={t(changeLabelKey(file.change))}
                      className={`shrink-0 rounded px-1 font-mono text-[11px] ${
                        CHANGE_MARK_CLASS[file.change] ?? CHANGE_MARK_CLASS.modified
                      }`}
                    >
                      {CHANGE_MARK[file.change] ?? '?'}
                    </span>
                    <span
                      className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200"
                      title={file.path}
                    >
                      {file.path}
                    </span>
                    {file.comparable ? (
                      <span className="shrink-0 font-mono text-[11px]">
                        <span className="text-emerald-600 dark:text-emerald-400">+{file.additions}</span>{' '}
                        <span className="text-rose-600 dark:text-rose-400">-{file.deletions}</span>
                      </span>
                    ) : (
                      <span className="shrink-0 text-[11px] text-slate-400 dark:text-slate-500">
                        {t('notComparable')}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="min-w-0 flex-1 overflow-hidden rounded-md border border-slate-200 dark:border-slate-700">
            {selectedFile === null ? (
              <p className="p-4 text-sm text-slate-500 dark:text-slate-400">{t('selectFile')}</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
                  <span className="min-w-0 truncate font-mono" title={selectedFile.path}>
                    {selectedFile.path}
                  </span>
                  {selectedPatch && selectedPatch.masked_secrets > 0 ? (
                    <span className="text-amber-600 dark:text-amber-400">
                      {t('maskedSecrets', { count: selectedPatch.masked_secrets })}
                    </span>
                  ) : null}
                </div>
                {!selectedFile.comparable ? (
                  <p className="p-4 text-sm text-slate-500 dark:text-slate-400">
                    {t(reasonKey(selectedFile.reason))}
                  </p>
                ) : selectedPatch?.patch ? (
                  <>
                    <DiffBody patch={selectedPatch.patch} />
                    {selectedPatch.truncated ? (
                      <p className="border-t border-slate-200 px-3 py-1.5 text-xs text-amber-600 dark:border-slate-700 dark:text-amber-400">
                        {t('patchTruncated')}
                      </p>
                    ) : null}
                  </>
                ) : (
                  <p className="p-4 text-sm text-slate-500 dark:text-slate-400">{t('patchOmitted')}</p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
