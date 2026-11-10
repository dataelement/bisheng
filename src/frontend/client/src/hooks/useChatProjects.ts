import { useEffect, useRef } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthContext } from '~/hooks/AuthContext';
import { fetchProjectConversations, fetchProjectSnapshot, performProjectAction, ProjectApiError, streamProjectEvents, newProjectRequestId } from '~/api/chatProjects';
import type { ProjectOperation } from '~/api/chatProjects';
import { readDesktopPresentation } from '~/utils/clientEnvironment';
import { QueryKeys } from '~/types/chat';

export type ProjectConnection = { phase: 'connecting' | 'live' | 'degraded' | 'offline' | 'auth_required'; revision: string };
const projectKey = (identity: string) => ['chat-projects', identity] as const;
const syncKey = (identity: string) => ['chat-projects-sync', identity] as const;

export function useProjectIdentity() {
  const { user, isAuthenticated } = useAuthContext();
  return isAuthenticated && user ? `${window.location.origin}:${user.tenant_id ?? 'pending'}:${user.id}` : '';
}

export function useChatProjects() {
  const identity = useProjectIdentity();
  const client = useQueryClient();
  return useQuery({
    queryKey: projectKey(identity), enabled: Boolean(identity), staleTime: 15000,
    refetchOnWindowFocus: false, retry: false,
    queryFn: async ({ signal }) => {
      const result = await fetchProjectSnapshot(signal ?? new AbortController().signal, () => client.getQueryData<ProjectConnection>(syncKey(identity))?.revision ?? '0');
      if (!identity.endsWith(`:${result.identity.tenant_id}:${result.identity.user_id}`)) throw new ProjectApiError();
      return result;
    },
  });
}

export function useProjectConnection() {
  const identity = useProjectIdentity();
  return useQuery<ProjectConnection>({ queryKey: syncKey(identity), enabled: false, initialData: { phase: 'connecting', revision: '0' } }).data;
}

export function useProjectConversations(projectId?: string, query = '', enabled = true) {
  const identity = useProjectIdentity();
  return useInfiniteQuery({
    queryKey: ['chat-projects-conversations', identity, projectId ?? '', query],
    enabled: enabled && Boolean(identity) && Boolean(projectId || query.trim()),
    queryFn: ({ signal, pageParam }) => fetchProjectConversations({ project_id: projectId, query, ...(typeof pageParam === 'string' ? { cursor: pageParam } : {}) }, signal),
    getNextPageParam: page => page.next_cursor ?? undefined,
    retry: false,
  });
}

export function useChatProjectActions() {
  const identity = useProjectIdentity();
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const client = useQueryClient();
  const pending = useRef(new Set<AbortController>());
  useEffect(() => () => { for (const controller of pending.current) controller.abort(); pending.current.clear(); }, [identity]);
  return useMutation({
    mutationFn: async ({ operation, requestId }: { operation: ProjectOperation; requestId?: string }) => {
      if (!identity) throw new ProjectApiError();
      const controller = new AbortController();
      pending.current.add(controller);
      try {
        const result = await performProjectAction(operation, requestId ?? newProjectRequestId(), controller.signal);
        if (currentIdentity.current !== identity || controller.signal.aborted) throw new DOMException('Identity changed', 'AbortError');
        client.setQueryData<ProjectConnection>(syncKey(identity), previous => ({ phase: result.notification, revision: BigInt(previous?.revision ?? '0') > BigInt(result.revision) ? previous?.revision ?? '0' : result.revision }));
        await client.invalidateQueries({ queryKey: projectKey(identity), exact: true }, { throwOnError: true });
        await Promise.all([
          client.invalidateQueries({ queryKey: ['chat-projects-conversations', identity] }),
          client.invalidateQueries({ queryKey: [QueryKeys.allConversations] }),
        ]);
        return result;
      } finally {
        pending.current.delete(controller);
      }
    },
  });
}

/** Mounted once in the authenticated shell, independently of sidebar visibility. */
export function useChatProjectSync() {
  const identity = useProjectIdentity();
  const client = useQueryClient();
  useChatProjects();
  useEffect(() => {
    if (!identity) return;
    const controller = new AbortController();
    let alive = true;
    let refreshing = false;
    let requested = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    const setState = (phase: ProjectConnection['phase'], revision?: string) => {
      if (!alive) return;
      client.setQueryData<ProjectConnection>(syncKey(identity), previous => ({ phase, revision: revision && BigInt(revision) > BigInt(previous?.revision ?? '0') ? revision : previous?.revision ?? '0' }));
    };
    const refresh = async () => {
      requested = true;
      if (refreshing) return;
      refreshing = true;
      try {
        while (requested && alive) {
          requested = false;
          await client.invalidateQueries({ queryKey: projectKey(identity), exact: true }, { throwOnError: true });
          await Promise.all([
            client.invalidateQueries({ queryKey: ['chat-projects-conversations', identity] }),
            client.invalidateQueries({ queryKey: [QueryKeys.allConversations] }),
          ]);
        }
      } catch (error) {
        if (alive) { setState('offline'); console.warn('[project-sync] refresh failed', error); }
      } finally { refreshing = false; }
    };
    const start = async () => {
      if (!alive) return;
      setState('connecting');
      try {
        await streamProjectEvents(controller.signal, (event, data) => {
          if (!alive) return;
          if (event === 'auth_required') {
            setState('auth_required');
            controller.abort();
            void client.cancelQueries({ queryKey: projectKey(identity) });
            client.removeQueries({ queryKey: projectKey(identity) });
            client.removeQueries({ queryKey: ['chat-projects-conversations', identity] });
            return;
          }
          attempt = 0;
          const previous = client.getQueryData<ProjectConnection>(syncKey(identity))?.revision ?? '0';
          setState(data.notification === 'degraded' ? 'degraded' : 'live', data.revision);
          const cached = client.getQueryData<{ revision: string }>(projectKey(identity));
          const failed = client.getQueryState(projectKey(identity))?.status === 'error' || client.getQueryCache().findAll({ queryKey: ['chat-projects-conversations', identity] }).some(query => query.state.status === 'error');
          if (event === 'ready' || failed || !cached || BigInt(cached.revision) < BigInt(data.revision) || BigInt(data.revision) > BigInt(previous)) void refresh();
        });
      } catch (error) {
        if (!alive || controller.signal.aborted) return;
        setState('offline');
        console.warn('[project-sync] subscription disconnected', error);
        const delays = [2000, 5000, 10000, 30000];
        retryTimer = setTimeout(() => void start(), (delays[Math.min(attempt++, 3)] ?? 30000) * (0.85 + Math.random() * 0.3));
      }
    };
    const host = readDesktopPresentation();
    const unsubscribe = host.onProjectsChanged?.(() => { setState('live'); void refresh(); });
    if (unsubscribe) { setState('live'); void refresh(); }
    else void start();
    const wake = () => { if (document.visibilityState === 'visible') void refresh(); };
    document.addEventListener('visibilitychange', wake);
    window.addEventListener('online', wake);
    return () => {
      alive = false; controller.abort(); clearTimeout(retryTimer); unsubscribe?.();
      document.removeEventListener('visibilitychange', wake); window.removeEventListener('online', wake);
      void client.cancelQueries({ queryKey: projectKey(identity) });
      void client.cancelQueries({ queryKey: ['chat-projects-conversations', identity] });
      client.removeQueries({ queryKey: projectKey(identity) });
      client.removeQueries({ queryKey: ['chat-projects-conversations', identity] });
      client.removeQueries({ queryKey: syncKey(identity) });
    };
  }, [identity, client]);
}
