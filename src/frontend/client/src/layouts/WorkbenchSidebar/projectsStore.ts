import { createLocalStore, useLocalStore } from '~/utils/localStore';

/**
 * MOCK: 项目 has no backend or data model yet. Projects the user creates live only in this
 * browser's localStorage so the sidebar interaction (create / rename / delete) can be
 * reviewed end to end. Swap this module for react-query hooks once the API exists — the
 * component only depends on the functions exported here.
 */
export interface MockProject {
  id: string;
  name: string;
  createdAt: number;
}

export const PROJECT_NAME_MAX_LENGTH = 30;

const projectsStore = createLocalStore<MockProject[]>('bs_mock_projects', [], (raw) =>
  Array.isArray(raw)
    ? raw.filter(
        (item): item is MockProject =>
          typeof item?.id === 'string' && typeof item?.name === 'string' && typeof item?.createdAt === 'number',
      )
    : [],
);

/**
 * MOCK: which project a conversation was moved into — conversationId → projectId.
 * A conversation belongs to at most one project, and the flat 对话 list hides the ones
 * that live in a project, the way the real feature is meant to behave.
 */
const projectChatsStore = createLocalStore<Record<string, string>>('bs_mock_project_chats', {}, (raw) => {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string',
    ),
  );
});

/** Newest first, like the conversation list below it. */
export function useMockProjects(): MockProject[] {
  return useLocalStore(projectsStore);
}

export function createMockProject(name: string): MockProject {
  const createdAt = Date.now();
  const project: MockProject = { id: `local-${createdAt.toString(36)}`, name, createdAt };
  projectsStore.set((prev) => [project, ...prev]);
  return project;
}

export function renameMockProject(id: string, name: string) {
  projectsStore.set((prev) => prev.map((project) => (project.id === id ? { ...project, name } : project)));
}

export function deleteMockProject(id: string) {
  projectsStore.set((prev) => prev.filter((project) => project.id !== id));
  // The conversations filed under it go back to the flat 对话 list rather than
  // disappearing with the folder.
  projectChatsStore.set((prev) => {
    const next = Object.fromEntries(Object.entries(prev).filter(([, projectId]) => projectId !== id));
    return Object.keys(next).length === Object.keys(prev).length ? prev : next;
  });
}

export function useMockProjectChats(): Record<string, string> {
  return useLocalStore(projectChatsStore);
}

export function moveChatToProject(conversationId: string, projectId: string) {
  projectChatsStore.set((prev) => ({ ...prev, [conversationId]: projectId }));
}

export function removeChatFromProject(conversationId: string) {
  projectChatsStore.set((prev) => {
    if (!(conversationId in prev)) return prev;
    const next = { ...prev };
    delete next[conversationId];
    return next;
  });
}
