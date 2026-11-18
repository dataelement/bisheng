import { useState } from 'react';
import { Button } from '@bisheng/ui';
import { ApiRequestFailure } from '~/components/ApiRequestFailure';
import { useLocalize } from '~/hooks';
import { useChatProjects } from '~/hooks/useChatProjects';
import { useProjectMigrationStatus } from '~/hooks/useProjectMigration';

const REASONS = ['not_owned', 'cloud_membership_kept', 'conversation_unavailable', 'invalid_local_data'];

export function ProjectSyncStatus() {
  const localize = useLocalize();
  const query = useChatProjects();
  const migration = useProjectMigrationStatus();
  const [resultLimit, setResultLimit] = useState(50);
  return <>
    {query.isError && <ApiRequestFailure error={query.error} onRetry={query.refetch} />}
    {migration.phase === 'busy' && <p role="status" className="px-2 text-caption text-text-3">{localize('project_sync.import_running')}</p>}
    {migration.phase === 'error' && <p role="status" className="px-2 text-caption text-text-3">{localize('project_sync.import_failed')}</p>}
    {migration.phase === 'done' && migration.skipped > 0 && <details className="px-2 text-caption text-text-3">
      <summary>{localize('project_sync.import_done', { count: migration.skipped })}</summary>
      <ul className="max-h-64 overflow-y-auto">{migration.details.slice(0, resultLimit).map((item, index) => <li key={index}>{item.id}: {localize(`project_sync.reason.${REASONS.includes(item.status) ? item.status : 'unknown'}`)}</li>)}</ul>
      {migration.details.length > resultLimit && <Button color="default" variant="text" onClick={() => setResultLimit(value => value + 50)}>{localize('project_sync.more')}</Button>}
    </details>}
  </>;
}
