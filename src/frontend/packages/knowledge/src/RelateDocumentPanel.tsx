import { Button, Input, Tooltip } from '@bisheng/ui';
import cn from '@bisheng/ui/cn';
import { Check, Link2, Loader2, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { RelationConfirmation } from './RelationConfirmation';
import { serviceIdentity } from './serviceIdentity';
import type { SearchableDocument, SimilarDocumentCandidate, SimilarDocumentEvents, SimilarDocumentFile, SimilarDocumentsServices } from './types';
import { useSimilarDocuments } from './useSimilarDocuments';
import { versionDialogStyles as styles } from './versionDialogStyles';

interface CandidateCardProps {
  entry: SimilarDocumentCandidate;
  disabled: boolean;
  onLink: (document: { document_id: number; title: string }) => void;
}

function RecommendationCard({ entry, disabled, onLink }: CandidateCardProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  const uploadTime = entry.primary_upload_time?.replace('T', ' ').slice(0, 16);
  const version = t('primary_version_label', { version: entry.current_primary_version_no ?? 1 });
  return (
    <div className={styles.candidateCard}>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <Tooltip content={entry.title} side="top"><p className="min-w-0 cursor-default truncate text-body font-medium text-text-1">{entry.title}</p></Tooltip>
          <span className="shrink-0 rounded bg-[#FFF3E8] px-1.5 py-0.5 text-caption text-[#F76F44]">{t('similarity_label')} {(entry.similarity * 100).toFixed(0)}%</span>
        </div>
        <p className="mb-0.5 text-caption text-text-3">{entry.doc_code ? `${entry.doc_code} · ${version}` : version}</p>
        {uploadTime && <p className="text-caption text-text-3">{entry.title} · {uploadTime}</p>}
      </div>
      <Button type="button" disabled={disabled} onClick={() => onLink({ document_id: entry.target_document_id, title: entry.title })} className="shrink-0">
        <Link2 />{t('btn_link_as_new_version')}
      </Button>
    </div>
  );
}

interface SearchResultRowProps {
  entry: SearchableDocument;
  disabled: boolean;
  onLink: CandidateCardProps['onLink'];
}

function SearchResultRow({ entry, disabled, onLink }: SearchResultRowProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  return (
    <div className="flex items-center justify-between gap-3 border-b border-fill-2 px-3 py-2.5 last:border-b-0 hover:bg-fill-1">
      <div className="min-w-0 flex-1">
        <p className="truncate text-body text-text-1">{entry.title}</p>
        <div className="mt-0.5 flex items-center gap-2 text-caption text-text-3">
          <span>V{entry.current_primary_version_no ?? 1}</span>
          {entry.doc_code && <span>{entry.doc_code}</span>}
          {entry.primary_uploader_name && <span>{entry.primary_uploader_name}</span>}
        </div>
      </div>
      <Button type="button" disabled={disabled} onClick={() => onLink({ document_id: entry.document_id, title: entry.title })} className="shrink-0">
        <Link2 />{t('btn_link_as_new_version')}
      </Button>
    </div>
  );
}

interface ErrorStateProps {
  error: unknown;
  onRetry: () => void;
}

function ErrorState({ error, onRetry }: ErrorStateProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  return <div role="alert" className="flex items-center justify-between gap-2 p-3 text-body text-text-2"><span>{error instanceof Error ? error.message : t('error')}</span><Button color="default" variant="outlined" onClick={onRetry}>{t('retry')}</Button></div>;
}

export interface RelateDocumentPanelProps extends SimilarDocumentEvents {
  spaceId: number;
  file: SimilarDocumentFile;
  services: SimilarDocumentsServices;
  mode?: 'merge' | 'link';
  className?: string;
  disabled?: boolean;
}

export function RelateDocumentPanel(props: RelateDocumentPanelProps) {
  return <RelateDocumentContent key={`${props.spaceId}:${props.file.id}:${serviceIdentity(props.services)}`} {...props} />;
}

function RelateDocumentContent({ spaceId, file, services, mode = 'merge', className, disabled = false, ...events }: RelateDocumentPanelProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  const state = useSimilarDocuments({ spaceId, fileId: file.id, services, ...events, linkSuccess: t('toast_link_success'), dismissSuccess: t('toast_dismiss_success') });
  const locked = disabled || state.busy || state.writeFailed || state.target !== null;
  const linking = mode === 'link';
  return (
    <div className={cn('flex h-full flex-col gap-5', className)}>
      <section className={`flex shrink-0 items-start justify-between ${styles.summary}`}>
        <div className="min-w-0 flex-1 pr-4">
          <p className="mb-1 text-caption text-text-3">{t('section_current_file')}</p>
          <Tooltip content={file.name} side="top"><p className="mb-1 truncate text-h4 font-medium text-text-1">{file.name}</p></Tooltip>
          <p className="text-caption text-text-3">{file.file_code ? `${file.file_code} · ` : ''}{t('primary_version_uploader', { version: file.version_no ?? 1, name: file.user_name ?? t('unknown') })}</p>
        </div>
        <span className="mt-1 shrink-0 rounded bg-[#FFF3E8] px-2 py-0.5 text-caption font-medium text-[#F76F44]">{t('current_file_recommend_pill', { count: file.candidate_count ?? state.candidates.length })}</span>
      </section>
      <div className={cn('flex shrink-0 flex-col rounded-lg border border-border-base', linking ? 'gap-5 bg-fill-1 p-4' : 'bg-bg-page')}>
        <section className={linking ? '' : 'border-b border-border-base p-4'}>
          <h3 className="mb-0.5 text-body font-medium text-text-1">{t('section_recommendations')}</h3>
          <p className="mb-3 text-caption text-text-3">{t(linking ? 'section_recommendations_subtitle' : 'section_recommendations_subtitle_merge')}</p>
          {state.candidatesLoading ? (
            <div className="flex h-16 items-center justify-center rounded-md border border-border-base bg-fill-1"><Loader2 className="size-5 animate-spin text-text-3" /></div>
          ) : state.candidatesError ? (
            <ErrorState error={state.candidatesError} onRetry={state.retryCandidates} />
          ) : state.candidates.length === 0 ? (
            <div className="flex h-[72px] items-center justify-center rounded-md border border-border-base bg-fill-1"><p className="text-body text-text-3">{t('no_recommendations')}</p></div>
          ) : (
            <div className={cn(styles.candidateList, !linking && 'rounded-md border border-border-base bg-fill-1 p-2')}>
              {state.candidates.map((entry) => <RecommendationCard key={entry.target_document_id} entry={entry} disabled={locked} onLink={state.selectTarget} />)}
            </div>
          )}
        </section>
        <section className={linking ? '' : 'p-4'}>
          <h3 className="mb-0.5 text-body font-medium text-text-1">{t('section_search')}</h3>
          <p className="mb-3 text-caption text-text-3">{t('section_search_subtitle')}</p>
          <div className="mb-3 flex gap-2">
            <Input type="text" value={state.keyword} onChange={(event) => state.setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); state.submitSearch(); } }} placeholder={t('search_placeholder')} aria-label={t('search_placeholder')} className="flex-1" />
            <Button type="button" color="default" variant="outlined" onClick={state.submitSearch}><Search />{t('search_button')}</Button>
          </div>
          {!state.search ? (
            <div className="flex h-16 items-center justify-center rounded-md border border-dashed border-border-base bg-fill-1"><p className="text-body text-text-4">{t('search_placeholder')}</p></div>
          ) : (
            <div className="rounded-md border border-border-base bg-bg-page">
              {state.searchLoading ? <div className="flex h-16 items-center justify-center"><Loader2 className="size-5 animate-spin text-text-3" /></div>
                : state.searchError ? <ErrorState error={state.searchError} onRetry={state.retrySearch} />
                  : state.searchResults.length === 0 ? <p className="px-3 py-4 text-body text-text-3">{t('no_search_results')}</p>
                    : <div className="scrollbar-on-scroll max-h-[220px] overflow-y-auto">{state.searchResults.map((entry) => <SearchResultRow key={entry.document_id} entry={entry} disabled={locked} onLink={state.selectTarget} />)}</div>}
            </div>
          )}
        </section>
      </div>
      <section className="mt-auto flex shrink-0 items-center justify-between rounded-lg border border-dashed border-border-base bg-bg-page px-4 py-3">
        <div><h3 className="mb-1 text-body font-medium text-text-1">{t('section_dismiss')}</h3><p className="text-caption text-text-3">{t('section_dismiss_subtitle')}</p></div>
        <Button type="button" color="default" variant="outlined" disabled={locked} onClick={() => void state.dismiss()} className="shrink-0"><Check />{t('btn_dismiss')}</Button>
      </section>
      {state.writeFailed && <p role="alert" className="text-body text-text-2">{t('uncertain')}</p>}
      <RelationConfirmation open={state.target !== null} busy={state.busy} onCancel={state.cancelTarget} onConfirm={() => void state.confirmTarget()} description={t(linking ? 'confirm_link_description' : 'confirm_merge_description', { name: file.name, target: state.target?.title ?? '' })} />
    </div>
  );
}
