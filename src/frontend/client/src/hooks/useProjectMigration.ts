import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { newProjectRequestId } from '~/api/chatProjects';
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

/** The first authenticated account claims unscoped legacy browser records.
 * Stable source/item receipts make interrupted batches safe to retry. */
export async function migrateLegacyProjects(
  identity: string,
  perform: (operation: ProjectOperation) => Promise<ProjectActionResult>,
  current: () => boolean,
): Promise<ProjectMigrationStatus> {
  const marker = `bs_project_import_done_v1:${identity}`;
  if (!identity || !current() || !hasLegacyProjects() || localStorage.getItem(marker)) return idle;
  let source = localStorage.getItem('bs_project_import_source_v1');
  if (!source) { source = newProjectRequestId(); localStorage.setItem('bs_project_import_source_v1', source); }
  const sourceId = source;
  const ownerKey = `bs_project_import_owner_v1:${source}`;
  const owner = localStorage.getItem(ownerKey);
  if (owner && owner !== identity) return idle;
  // Freeze the destination before any request; switching accounts cannot adopt
  // these same unscoped records or continue a previous account's batches.
  if (!owner) localStorage.setItem(ownerKey, identity);
  const legacy = readLegacyProjects();
  let skipped = legacy.skipped;
  const details = [...legacy.invalid];
  const submit = async (projects: typeof legacy.projects, memberships: typeof legacy.memberships) => {
    if (!current()) throw new DOMException('Identity changed', 'AbortError');
    const result = await perform({ operation: 'import', source_client_id: sourceId, projects, memberships });
    if (!current()) throw new DOMException('Identity changed', 'AbortError');
    for (const item of result.outcome.items ?? []) {
      if (item.status === 'imported') continue;
      skipped++;
      details.push({ id: item.chat_id ?? item.legacy_id ?? '', status: item.status });
    }
  };
  for (let offset = 0; offset < legacy.projects.length; offset += 100) await submit(legacy.projects.slice(offset, offset + 100), []);
  for (let offset = 0; offset < legacy.memberships.length; offset += 500) await submit([], legacy.memberships.slice(offset, offset + 500));
  if (!current()) throw new DOMException('Identity changed', 'AbortError');
  localStorage.setItem(marker, source);
  return { phase: 'done', skipped, details };
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
        console.warn('[project-sync] automatic legacy migration failed', error);
        timer = setTimeout(() => void run(), [2000, 5000, 10000, 30000][Math.min(attempt++, 3)] ?? 30000);
      }
    };
    void run();
    return () => { alive = false; clearTimeout(timer); };
  }, [identity, ready, client, mutateAsync]);
}
