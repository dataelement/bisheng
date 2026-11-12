import { useEffect, useRef } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthContext } from '~/hooks/AuthContext';
import { fetchProjectConversations, fetchProjectSnapshot, performProjectAction, ProjectApiError } from '~/api/chatProjects';
import type { ProjectOperation } from '~/api/chatProjects';
import { readDesktopPresentation } from '~/utils/clientEnvironment';
import { QueryKeys } from '~/types/chat';

const projectKey = (identity: string) => ['chat-projects', identity] as const;

export function useProjectIdentity() {
  const { user, isAuthenticated } = useAuthContext();
  return isAuthenticated && user ? `${window.location.origin}:${user.tenant_id ?? 'pending'}:${user.id}` : '';
}

/** Server state only. Another client's changes appear on focus, reconnect or the next mutation,
 *  the same way the ordinary conversation list updates; there is no push channel. */
export function useChatProjects() {
  const identity = useProjectIdentity();
  return useQuery({
    queryKey: projectKey(identity), enabled: Boolean(identity), staleTime: 15000,
    refetchOnWindowFocus: true, refetchOnReconnect: true, retry: false,
    queryFn: async ({ signal }) => {
      const result = await fetchProjectSnapshot(signal);
      if (!identity.endsWith(`:${result.identity.tenant_id}:${result.identity.user_id}`)) throw new ProjectApiError();
      return result;
    },
  });
}

export function useProjectConversations(projectId?: string, query = '', enabled = true) {
  const identity = useProjectIdentity();
  return useInfiniteQuery({
    queryKey: ['chat-projects-conversations', identity, projectId ?? '', query],
    enabled: enabled && Boolean(identity) && Boolean(projectId || query.trim()),
    queryFn: ({ signal, pageParam }) => fetchProjectConversations({ project_id: projectId, query, ...(typeof pageParam === 'string' ? { cursor: pageParam } : {}) }, signal),
    getNextPageParam: page => page.next_cursor ?? undefined,
    refetchOnWindowFocus: true,
    retry: false,
  });
}

function invalidateProjects(client: ReturnType<typeof useQueryClient>, identity: string) {
  return Promise.all([
    client.invalidateQueries({ queryKey: projectKey(identity), exact: true }),
    client.invalidateQueries({ queryKey: ['chat-projects-conversations', identity] }),
    client.invalidateQueries({ queryKey: [QueryKeys.allConversations] }),
  ]);
}

export function useChatProjectActions() {
  const identity = useProjectIdentity();
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const client = useQueryClient();
  const pending = useRef(new Set<AbortController>());
  useEffect(() => () => { for (const controller of pending.current) controller.abort(); pending.current.clear(); }, [identity]);
  return useMutation({
    mutationFn: async ({ operation }: { operation: ProjectOperation }) => {
      if (!identity) throw new ProjectApiError();
      const controller = new AbortController();
      pending.current.add(controller);
      try {
        const result = await performProjectAction(operation, controller.signal);
        if (currentIdentity.current !== identity || controller.signal.aborted) throw new DOMException('Identity changed', 'AbortError');
        await invalidateProjects(client, identity);
        return result;
      } finally {
        pending.current.delete(controller);
      }
    },
  });
}

/** Mounted once in the authenticated shell: the desktop host may hint that projects changed. */
export function useDesktopProjectRefresh() {
  const identity = useProjectIdentity();
  const client = useQueryClient();
  useEffect(() => {
    if (!identity) return;
    return readDesktopPresentation().onProjectsChanged?.(() => { void invalidateProjects(client, identity); });
  }, [identity, client]);
}
