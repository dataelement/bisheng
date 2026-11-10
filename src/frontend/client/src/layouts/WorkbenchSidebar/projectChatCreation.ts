import { hasMockProject, moveChatToProject } from './projectsStore';

/** Capture the draft's project before opening a stream: later events may arrive
 *  after navigation to a different project or conversation. */
export function captureProjectChatCreation(conversationId: unknown, customEndpoint?: string) {
  const url = new URL(window.location.href);
  const projectId = url.searchParams.get('projectId');
  const isProjectDraft = !customEndpoint && !conversationId && /\/c\/new\/?$/.test(url.pathname);
  let assigned = false;

  return (createdId: string) => {
    if (assigned || !isProjectDraft || !projectId || !createdId || createdId === 'new' || !hasMockProject(projectId)) return;
    assigned = true;
    moveChatToProject(createdId, projectId);
  };
}
