export type ProjectIntent = { project_id: string };
export type ProjectChatDraft = Readonly<{ projectId: string }>;

function isWorkstationEndpoint(value: string): boolean {
  try {
    const endpoint = new URL(value, window.location.origin);
    return endpoint.origin === window.location.origin && !endpoint.search && !endpoint.hash &&
      /^\/(?:workspace\/)?api\/v1\/workstation\/chat\/completions\/?$/.test(endpoint.pathname);
  } catch { return false; }
}

/** Capture the draft before asynchronous upload/lease work can change the route. */
export function captureProjectChatDraft(conversationId: unknown, customEndpoint?: string): ProjectChatDraft | undefined {
  const url = new URL(window.location.href);
  const projectId = url.searchParams.get('projectId');
  if ((customEndpoint && !isWorkstationEndpoint(customEndpoint)) || conversationId || !/\/c\/new\/?$/.test(url.pathname) ||
      !projectId || !/^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$/.test(projectId)) return;
  return Object.freeze({ projectId });
}

/** The server creates the conversation and its membership in one transaction. */
export function bindProjectChatCreation(draft: ProjectChatDraft | undefined): ProjectIntent | undefined {
  return draft ? { project_id: draft.projectId } : undefined;
}
