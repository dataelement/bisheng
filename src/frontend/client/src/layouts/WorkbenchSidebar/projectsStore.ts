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
}
