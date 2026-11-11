import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { ProjectOperation, ProjectActionResult } from '~/api/chatProjects';
import { hasLegacyProjects, readLegacyProjects } from '~/layouts/WorkbenchSidebar/projectsStore';
import { useChatProjectActions, useChatProjects, useProjectIdentity } from './useChatProjects';

export type ProjectMigrationStatus = {
  phase: 'idle' | 'busy' | 'done' | 'error';
  skipped: number;
  details: Array<{ id: string; status: string }>;
};
const migrationKey = (identity: string) => ['chat-projects-migration', identity] as const;
const idle: ProjectMigrationStatus = { phase: 'idle', skipped: 0, details: [] };
/** Outcomes that mean nothing was lost for this account: no need to report them. */
const quiet = new Set(['imported', 'already_imported']);

/** Each account imports the legacy projects it owns. The browser record has no account,
 *  so the server infers ownership from the conversations and ignores the rest. */
export async function migrateLegacyProjects(
  identity: string,
  perform: (operation: ProjectOperation) => Promise<ProjectActionResult>,
  current: () => boolean,
): Promise<ProjectMigrationStatus> {
  const marker = `bs_project_import_done_v2:${identity}`;
  // v1 imports used random project ids; importing again under the deterministic
  // ids of v2 would duplicate every project, so an account done under v1 stays done.
  const doneUnderV1 = localStorage.getItem(`bs_project_import_done_v1:${identity}`);
  if (!identity || !current() || !hasLegacyProjects() || localStorage.getItem(marker) || doneUnderV1) return idle;
  const legacy = readLegacyProjects();
  const result = await perform({ operation: 'import', projects: legacy.projects, memberships: legacy.memberships });
  if (!current()) throw new DOMException('Identity changed', 'AbortError');
  const details = [...legacy.invalid];
  for (const item of result.outcome.items ?? []) {
    if (!quiet.has(item.status)) details.push({ id: item.chat_id ?? item.legacy_id ?? '', status: item.status });
  }
  localStorage.setItem(marker, '1');
  return { phase: 'done', skipped: details.length, details };
}

export function useProjectMigrationStatus() {
  const identity = useProjectIdentity();
  return useQuery<ProjectMigrationStatus>({ queryKey: migrationKey(identity), enabled: false, initialData: idle }).data ?? idle;
}

/** Mounted once in the authenticated shell, including when the sidebar is hidden. */
export function useProjectMigration() {
  const identity = useProjectIdentity();
  const client = useQueryClient();
  const query = useChatProjects();
  const { mutateAsync } = useChatProjectActions();
  const ready = query.isSuccess;
  useEffect(() => {
    if (!identity || !ready) return;
    let alive = true;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      if (!alive) return;
      client.setQueryData(migrationKey(identity), { ...idle, phase: 'busy' });
      try {
        const status = await migrateLegacyProjects(identity, operation => mutateAsync({ operation }), () => alive);
        if (alive) client.setQueryData(migrationKey(identity), status);
      } catch (error) {
        if (!alive) return;
        client.setQueryData(migrationKey(identity), { ...idle, phase: 'error' });
        console.warn('[projects] automatic legacy migration failed', error);
        timer = setTimeout(() => void run(), [2000, 5000, 10000, 30000][Math.min(attempt++, 3)] ?? 30000);
      }
    };
    void run();
    return () => { alive = false; clearTimeout(timer); };
  }, [identity, ready, client, mutateAsync]);
}
