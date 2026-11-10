import { newProjectRequestId } from '~/api/chatProjects';
import { readNewChatKey } from '~/components/Chat/newChatDraft';

export type ProjectIntent = { project_id: string; project_request_id: string };
export type ProjectChatDraft = Readonly<{ projectId: string; entryKey: string; href: string }>;
const intents = new WeakMap<object, ProjectIntent>();

function isWorkstationEndpoint(value: string): boolean {
  try {
    const endpoint = new URL(value, window.location.origin);
    return endpoint.origin === window.location.origin && !endpoint.search && !endpoint.hash &&
      /^\/(?:workspace\/)?api\/v1\/workstation\/chat\/completions\/?$/.test(endpoint.pathname);
  } catch { return false; }
}

/** A non-secret fingerprint: the server independently verifies the full request. */
function fingerprint(value: string): string {
  let forward = 2166136261, reverse = 2166136261;
  for (let index = 0; index < value.length; index++) {
    forward = Math.imul(forward ^ value.charCodeAt(index), 16777619);
    reverse = Math.imul(reverse ^ value.charCodeAt(value.length - index - 1), 16777619);
  }
  return (forward >>> 0).toString(16) + (reverse >>> 0).toString(16);
}

/** Capture the draft before asynchronous upload/lease work can change the route. */
export function captureProjectChatDraft(conversationId: unknown, customEndpoint?: string): ProjectChatDraft | undefined {
  const url = new URL(window.location.href);
  const projectId = url.searchParams.get('projectId');
  if ((customEndpoint && !isWorkstationEndpoint(customEndpoint)) || conversationId || !/\/c\/new\/?$/.test(url.pathname) ||
      !projectId || !/^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$/.test(projectId)) return;
  const entry: unknown = window.history.state;
  const routerKey = entry && typeof entry === 'object' && 'key' in entry && typeof entry.key === 'string' ? entry.key : 'default';
  const routeState = entry && typeof entry === 'object' && 'usr' in entry ? entry.usr : undefined;
  const entryKey = readNewChatKey(routeState, routerKey);
  return Object.freeze({ projectId, entryKey, href: url.href });
}

/** Bind a captured draft to this exact request. Created callbacks never write metadata. */
export function bindProjectChatCreation(draft: ProjectChatDraft | undefined, payload: Record<string, unknown>): ProjectIntent | undefined {
  if (!draft) return;
  const cached = intents.get(payload);
  if (cached) return cached;
  const key = 'bs_project_draft_v1:' + fingerprint(draft.projectId + ':' + draft.entryKey);
  const content = Object.fromEntries(Object.entries(payload).filter(([name]) =>
    !['clientTimestamp', 'generation', 'error', 'messageId', 'responseMessageId', 'parentMessageId', 'overrideParentMessageId'].includes(name)));
  const digest = fingerprint(JSON.stringify(content));
  let requestId = newProjectRequestId();
  try {
    const previous: unknown = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    if (previous && typeof previous === 'object' && 'digest' in previous && previous.digest === digest &&
        'requestId' in previous && typeof previous.requestId === 'string') requestId = previous.requestId;
    sessionStorage.setItem(key, JSON.stringify({ digest, requestId }));
    const keys = Object.keys(sessionStorage).filter(name => name.startsWith('bs_project_draft_v1:'));
    for (const stale of keys.slice(0, Math.max(0, keys.length - 64))) if (stale !== key) sessionStorage.removeItem(stale);
  } catch (error) {
    // The in-flight payload still retains its id when browser storage is disabled.
    console.warn('[project-sync] draft retry storage unavailable', error);
  }
  const intent = { project_id: draft.projectId, project_request_id: requestId };
  intents.set(payload, intent);
  return intent;
}

/** Immediate callers may capture and bind in the same synchronous operation. */
export function captureProjectChatCreation(conversationId: unknown, customEndpoint?: string, payload: Record<string, unknown> = {}): ProjectIntent | undefined {
  return bindProjectChatCreation(captureProjectChatDraft(conversationId, customEndpoint), payload);
}
