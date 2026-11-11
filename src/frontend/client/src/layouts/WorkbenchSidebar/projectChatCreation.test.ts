import { bindProjectChatCreation, captureProjectChatDraft } from './projectChatCreation';

const project = '11111111-1111-4111-8111-111111111111';
const capture = (conversationId: unknown, endpoint?: string) => bindProjectChatCreation(captureProjectChatDraft(conversationId, endpoint));
beforeEach(() => { window.history.replaceState({ key: 'draft-one' }, '', `/workspace/c/new?projectId=${project}`); });

it('captures immutable intent before the route changes', () => {
  const draft = captureProjectChatDraft(null);
  window.history.replaceState({}, '', '/workspace/c/new');
  expect(bindProjectChatCreation(draft)).toEqual({ project_id: project });
  expect(capture(null)).toBeUndefined();
});

it('does not inherit intent in existing chats or custom endpoints', () => {
  expect(capture('existing')).toBeUndefined();
  expect(capture(null, '/subscription/chat')).toBeUndefined();
});

it.each(['/workspace/api/v1/workstation/chat/completions', '/api/v1/workstation/chat/completions'])('keeps project intent for an explicit ordinary workstation endpoint: %s', endpoint => {
  expect(capture(null, endpoint)?.project_id).toBe(project);
  expect(capture(null, window.location.origin + endpoint)?.project_id).toBe(project);
});

it('does not send project metadata to the same path on another origin', () => {
  expect(capture(null, 'https://other.invalid/workspace/api/v1/workstation/chat/completions')).toBeUndefined();
});
