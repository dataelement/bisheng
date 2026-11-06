import { captureProjectChatCreation } from './projectChatCreation';

const project = '11111111-1111-4111-8111-111111111111';
beforeEach(() => { sessionStorage.clear(); window.history.replaceState({ key: 'draft-one' }, '', `/workspace/c/new?projectId=${project}`); });

it('captures immutable intent and reuses the id for the same draft retry', () => {
  const one = captureProjectChatCreation(null, undefined, { text: 'Hello', clientTimestamp: '1' });
  const retry = captureProjectChatCreation(null, undefined, { text: 'Hello', clientTimestamp: '2' });
  expect(one?.project_id).toBe(project);
  expect(one?.project_request_id).toBe(retry?.project_request_id);
  window.history.replaceState({}, '', '/workspace/c/new');
  expect(one?.project_id).toBe(project);
  expect(captureProjectChatCreation(null)).toBeUndefined();
});

it('does not inherit intent in existing chats or custom endpoints', () => {
  expect(captureProjectChatCreation('existing')).toBeUndefined();
  expect(captureProjectChatCreation(null, '/subscription/chat')).toBeUndefined();
});

it.each(['/workspace/api/v1/workstation/chat/completions', '/api/v1/workstation/chat/completions'])('keeps project intent for an explicit ordinary workstation endpoint: %s', endpoint => {
  expect(captureProjectChatCreation(null, endpoint)?.project_id).toBe(project);
  expect(captureProjectChatCreation(null, window.location.origin + endpoint)?.project_id).toBe(project);
});

it('does not send project metadata to the same path on another origin', () => {
  expect(captureProjectChatCreation(null, 'https://other.invalid/workspace/api/v1/workstation/chat/completions')).toBeUndefined();
});

it('keeps retry identity through both reset passes of one logical draft', () => {
  window.history.replaceState({ key: 'first-router-key', usr: { newChatKey: 'one-intent' } }, '', window.location.href);
  const first = captureProjectChatCreation(null, undefined, { text: 'Question', messageId: 'first-ui-id' });
  window.history.replaceState({ key: 'second-router-key', usr: { newChatKey: 'one-intent' } }, '', window.location.href);
  const retry = captureProjectChatCreation(null, undefined, { text: 'Question', messageId: 'retry-ui-id' });
  expect(retry?.project_request_id).toBe(first?.project_request_id);
});

it('keeps an initial browser draft retry identity after settings saves its default key', () => {
  window.history.replaceState(null, '', `/workspace/c/new?projectId=${project}`);
  const first = captureProjectChatCreation(null, undefined, { text: 'Question', messageId: 'first-id' });
  window.history.replaceState({ key: 'return-key', usr: { newChatKey: 'default' } }, '', window.location.href);
  const retry = captureProjectChatCreation(null, undefined, { text: 'Question', messageId: 'retry-id' });
  expect(retry?.project_request_id).toBe(first?.project_request_id);
});
