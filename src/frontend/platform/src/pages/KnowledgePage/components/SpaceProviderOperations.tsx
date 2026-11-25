import { Button, Pagination } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '@/components/bs-icons/loading/LoadingState';
import { readProviderOperations } from '@/controllers/API/knowledgeProviderOperations';
import { knowledgeQueryKeys, type KnowledgeQueryScope } from '@/controllers/hooks/knowledge';
import { usePaginationLocale } from '@/hooks/usePaginationLocale';

interface Props { scope: KnowledgeQueryScope; spaceId: number }
const pageSize = 20;

export function SpaceProviderOperations({ scope, spaceId }: Props) {
  const { t } = useTranslation('knowledge');
  const locale = usePaginationLocale();
  const [page, setPage] = useState(1);
  const result = useQuery({
    queryKey: [...knowledgeQueryKeys.space(scope, spaceId), 'provider-operations', page, pageSize],
    queryFn: ({ signal }) => readProviderOperations(spaceId, page, pageSize, signal),
    cacheTime: 0, keepPreviousData: false, retry: false,
  });
  if (result.isError) return <div role="alert" className="flex items-center gap-2">
    {t('provider_operations.unavailable')}
    <Button variant="text" disabled={result.isFetching} onClick={() => { void result.refetch(); }}>{t('retry')}</Button>
  </div>;
  if (!result.data) return <LoadingState label={t('loading')} />;
  return <section aria-label={t('provider_operations.title')} className="flex min-h-0 flex-1 flex-col gap-3">
    <p className="text-sm text-text-2">{t('provider_operations.unverified')}</p>
    <div className="min-h-0 flex-1 overflow-auto" key={page}>
      {result.data.total === 0 && <p role="status">{t('provider_operations.empty')}</p>}
      <ul className="divide-y divide-border-base">
        {result.data.data.map((row, index) => <li key={row.operationId ?? index} className="py-3">
          <h3 className="text-sm font-medium"><span>{t(`provider_operations.kinds.${row.kind}`)}</span> · <span>{t(`provider_operations.states.${row.state}`)}</span></h3>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            {[
              ['operation', row.operationId], ['space', row.spaceId], ['versions', row.versionIds.join(', ') || null],
              ['target', row.remoteTarget], ['generation', row.generation], ['phase', t(`provider_operations.phases.${row.phase}`)],
              ['attempt', row.attempt], ['error', row.errorCode && t(`provider_operations.errors.${row.errorCode}`)],
              ['capability_revision', row.capabilityRevision],
            ].map(([field, value]) => <Fragment key={field}>
              <dt className="text-text-3">{t(`provider_operations.${field}`)}</dt><dd className="break-words">{value ?? '—'}</dd>
            </Fragment>)}
          </dl>
        </li>)}
      </ul>
    </div>
    <Pagination current={page} onChange={setPage} total={result.data.total} pageSize={pageSize} locale={locale} />
  </section>;
}
