import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  buildKunlianWorkflowEditPath,
  buildKunlianWorkflowRunPath,
  claimKunlianWorkflowLoginAttempt,
  clearKunlianWorkflowLoginAttempt,
  KUNLIAN_WORKFLOW_ATTEMPT_KEY,
  KUNLIAN_WORKFLOW_ATTEMPT_TTL_MS,
  KunlianBrowserFlow,
  kunlianLoginUrl,
  parseKunlianWorkflowEntry,
  safeKunlianReturnTo,
} from './index';
import type { KunlianWorkflowEntry, KunlianWorkflowEntryStorage } from './index';

// Covers AC-05, AC-07, AC-08, AC-09 at the shared-rule boundary only.
const workflowId = '0123456789abcdef0123456789abcdef';
const chatId = 'abcdef0123456789abcdef0123456789';
const edit = `/flow/${workflowId}?from=workflow-management&entry=kunlian`;
const run = `/workspace/app/${workflowId}/10?entry=kunlian`;
const conversation = `/workspace/app/${chatId}/${workflowId}/10?entry=kunlian`;
const now = 1_000_000;

function memoryStorage(): KunlianWorkflowEntryStorage {
  const items = new Map<string, string>();
  return {
    getItem: key => items.get(key) ?? null,
    setItem: (key, value) => { items.set(key, value); },
    removeItem: key => { items.delete(key); },
  };
}

function active(raw = run): KunlianWorkflowEntry {
  const entry = parseKunlianWorkflowEntry(raw);
  if (entry.kind !== 'edit' && entry.kind !== 'run') throw new Error('Expected active entry');
  return entry;
}

afterEach(() => { vi.unstubAllGlobals(); });

describe('workflow link contract', () => {
  it('builds the two public paths and retains the workspace basename for a conversation', () => {
    expect(buildKunlianWorkflowEditPath(workflowId)).toBe(edit);
    expect(buildKunlianWorkflowRunPath(workflowId)).toBe(run);
    expect(buildKunlianWorkflowRunPath(workflowId, chatId)).toBe(conversation);
    for (const target of [edit, run, conversation]) {
      expect(safeKunlianReturnTo(target)).toBe(target);
      expect(kunlianLoginUrl(target)).toBe(`/api/oauth2/kunlian?return_to=${encodeURIComponent(target)}`);
    }
  });

  it.each([
    [edit, { kind: 'edit', workflowId, returnTo: edit }],
    [run, { kind: 'run', workflowId, returnTo: run }],
    [conversation, { kind: 'run', workflowId, chatId, returnTo: conversation }],
  ])('parses only the declared workflow target: %s', (raw, expected) => {
    expect(parseKunlianWorkflowEntry(raw)).toEqual(expected);
  });

  it('normalizes query order and a trailing slash without losing the target', () => {
    expect(active(`/flow/${workflowId}/?entry=kunlian&from=workflow-management`)).toEqual(active(edit));
  });

  it.each([
    '/build/workflows',
    `/flow/${workflowId}?from=workflow-management`,
    `/workspace/app/${workflowId}/10?from=home-recommended&entry=home`,
    '/workspace/c/new',
  ])('leaves unrelated existing entries alone: %s', raw => {
    expect(parseKunlianWorkflowEntry(raw)).toEqual({ kind: 'not-entry' });
  });

  it.each([
    `https://foreign.fixture.invalid${run}`,
    `//foreign.fixture.invalid${run}`,
    run.replace('/workspace/', '/workspace//'),
    run.replace('/workspace/', '/workspace/../workspace/'),
    run.replace('/workspace/', '/workspace/%2e%2e/workspace/'),
    run.replace('/workspace/', '/workspace/%252e%252e/workspace/'),
    run.replace('/app/', '/app%2f'),
    run.replace('/app/', '/app\\'),
    run.replace('/app/', '/app\n'),
    `${run}#foreign-fragment`,
    `${run}%`,
    `${run}%0a`,
    `${run}&entry=kunlian`,
    `${run}&entry=home`,
    run.replace('entry=kunlian', 'entry=KUNLIAN'),
    `${run}&token=fixture`,
    `${run}&%74oken=fixture`,
    `${run}&TOKEN=fixture`,
    `${run}&access_token=fixture`,
    `${run}&user_id=17`,
    `${run}&tenant_id=2`,
    `${run}&version_id=1`,
    `${run}&return_to=https://foreign.fixture.invalid`,
    `${run}&extra=unregistered`,
    run.replace('/10?', '/5?'),
    run.replace(workflowId, 'not-a-workflow-id'),
    edit.replace('from=workflow-management&', ''),
    edit.replace('from=workflow-management', 'from=foreign'),
    '/build/workflows?entry=kunlian',
    `${run}&status_code=200`,
    `${run}&status_code=19320&status_code=19320`,
    `${run}&extra=${'x'.repeat(2048)}`,
  ])('rejects an unsafe marked entry without reducing it to a different valid target: %s', raw => {
    expect(parseKunlianWorkflowEntry(raw)).toEqual({ kind: 'invalid-entry' });
  });

  it('keeps a known authentication failure as evidence but removes it from the retry target', () => {
    expect(active(`${edit}&status_code=19321`)).toEqual({
      kind: 'edit', workflowId, returnTo: edit, failureCode: 19321,
    });
  });

  it.each(['', 'fixture', '../fixture', workflowId + '/extra', workflowId.toUpperCase()])('refuses invalid builder IDs: %s', id => {
    expect(() => buildKunlianWorkflowEditPath(id)).toThrow('KUNLIAN_WORKFLOW_ENTRY_INVALID');
    expect(() => buildKunlianWorkflowRunPath(workflowId, id)).toThrow('KUNLIAN_WORKFLOW_ENTRY_INVALID');
  });
});

describe('tab-scoped login attempts', () => {
  it('allows one automatic attempt per workflow and action, including after a new document or chat redirect', () => {
    const storage = memoryStorage();
    const options = { storage, now, callback: false };
    expect(claimKunlianWorkflowLoginAttempt(active(), options)).toBe(true);
    expect(claimKunlianWorkflowLoginAttempt(active(), options)).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(active(conversation), options)).toBe(false);
    expect(JSON.parse(storage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY)!)).toEqual({
      kind: 'run', workflowId, returnTo: run, startedAt: now,
    });
    expect(claimKunlianWorkflowLoginAttempt(active(edit), options)).toBe(true);
  });

  it('blocks automatic callback and failed-entry retries, but permits an explicit retry of the original target', () => {
    const storage = memoryStorage();
    const failed = active(`${run}&status_code=19323`);
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now, callback: true })).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(failed, { storage, now, callback: false })).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(failed, { storage, now, callback: true, manual: true })).toBe(true);
    expect(JSON.parse(storage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY)!)).toEqual({
      kind: 'run', workflowId, returnTo: run, startedAt: now,
    });
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now: now + 1, callback: false })).toBe(false);
  });

  it('expires exactly after ten minutes and only clears a successful matching target', () => {
    const storage = memoryStorage();
    expect(KUNLIAN_WORKFLOW_ATTEMPT_TTL_MS).toBe(10 * 60 * 1000);
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now, callback: false })).toBe(true);
    expect(claimKunlianWorkflowLoginAttempt(active(), {
      storage, now: now + KUNLIAN_WORKFLOW_ATTEMPT_TTL_MS - 1, callback: false,
    })).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(active(), {
      storage, now: now + KUNLIAN_WORKFLOW_ATTEMPT_TTL_MS, callback: false,
    })).toBe(true);
    expect(clearKunlianWorkflowLoginAttempt(active(edit), storage)).toBe(false);
    expect(storage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY)).not.toBeNull();
    expect(clearKunlianWorkflowLoginAttempt(active(conversation), storage)).toBe(true);
    expect(storage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY)).toBeNull();
  });

  it.each(['unreadable', 'unwritable', 'unverified-write'])('does not authorize automatically when storage is %s', failure => {
    const storage = memoryStorage();
    if (failure === 'unreadable') storage.getItem = () => { throw new Error('Storage unavailable'); };
    if (failure === 'unwritable') storage.setItem = () => { throw new Error('Storage unavailable'); };
    if (failure === 'unverified-write') storage.setItem = () => undefined;
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now, callback: false })).toBe(false);
  });

  it.each([
    'not-json', 'null', '{}',
    JSON.stringify({ kind: 'run', workflowId, returnTo: run, startedAt: now + 1 }),
    JSON.stringify({ kind: 'run', workflowId, returnTo: 'https://foreign.fixture.invalid', startedAt: now }),
    JSON.stringify({ kind: 'run', workflowId, returnTo: run, startedAt: now, token: 'fixture' }),
  ])('fails closed on corrupt or future-dated state and allows manual recovery: %s', record => {
    const storage = memoryStorage();
    storage.setItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY, record);
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now, callback: false })).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now, callback: false, manual: true })).toBe(true);
  });

  it('requires a known non-callback phase before claiming automatic navigation', () => {
    const storage = memoryStorage();
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now })).toBe(false);
    expect(storage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY)).toBeNull();
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now, manual: true })).toBe(true);
  });

  it('does not fall back to persistent state when sessionStorage is denied or cleanup fails', () => {
    const storage = memoryStorage();
    vi.stubGlobal('sessionStorage', storage);
    expect(claimKunlianWorkflowLoginAttempt(active(), { now, callback: false })).toBe(true);
    expect(clearKunlianWorkflowLoginAttempt(active(run.replace(workflowId, 'a'.repeat(32))), storage)).toBe(false);
    storage.removeItem = () => { throw new Error('Storage unavailable'); };
    expect(clearKunlianWorkflowLoginAttempt(active(), storage)).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(active(), { now, callback: false })).toBe(false);
    Object.defineProperty(globalThis, 'sessionStorage', {
      configurable: true,
      get() { throw new Error('Storage access denied'); },
    });
    expect(claimKunlianWorkflowLoginAttempt(active(), { now, callback: false })).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(active(), { now, manual: true })).toBe(true);
    expect(clearKunlianWorkflowLoginAttempt(active())).toBe(false);
  });

  it('validates runtime targets and does not navigate, call HTTP or write identity state', () => {
    const request = vi.fn();
    vi.stubGlobal('fetch', request);
    vi.stubGlobal('document', { cookie: 'unchanged' });
    vi.stubGlobal('location', { href: 'https://app.fixture.invalid/unchanged' });
    const storage = memoryStorage();
    storage.setItem('LOGIN_PATHNAME', 'https://foreign.fixture.invalid');
    storage.setItem('ws_token', 'fixture-old-hint');
    const unsafe = { ...active(), returnTo: 'https://foreign.fixture.invalid' };
    expect(claimKunlianWorkflowLoginAttempt(unsafe, { storage, now, callback: false })).toBe(false);
    expect(claimKunlianWorkflowLoginAttempt(active(), { storage, now, callback: false })).toBe(true);
    expect(request).not.toHaveBeenCalled();
    expect(document.cookie).toBe('unchanged');
    expect(location.href).toBe('https://app.fixture.invalid/unchanged');
    expect(storage.getItem('LOGIN_PATHNAME')).toBe('https://foreign.fixture.invalid');
    expect(storage.getItem('ws_token')).toBe('fixture-old-hint');
  });
});

describe('callback phase remains evidence, not identity', () => {
  it('retains callback origin after the hash is consumed and does not accept a different identity source', () => {
    const replaceState = vi.fn();
    const local = memoryStorage();
    local.setItem('ws_token', 'fixture-old-hint');
    vi.stubGlobal('localStorage', local);
    vi.stubGlobal('location', { pathname: `/flow/${workflowId}`, search: '?entry=kunlian', hash: '#kunlian-login' });
    vi.stubGlobal('history', { state: null, replaceState });
    const flow = new KunlianBrowserFlow();
    expect(replaceState).toHaveBeenCalledWith(null, '', `/flow/${workflowId}?entry=kunlian`);
    expect(local.getItem('ws_token')).toBeNull();
    location.hash = '';
    expect(flow.isCallbackEntry()).toBe(true);
    expect(flow.confirmUser({ user_id: 7 })).toBe(false);
    expect(flow.requiresManualLogin()).toBe(true);
    expect(flow.confirmUser({ user_id: 7, auth_source: 'kunlian' })).toBe(true);
    expect(flow.isCallbackEntry()).toBe(true);
    flow.resetAfterExplicitLogin();
    expect(flow.isCallbackEntry()).toBe(true);
    expect(flow.isKunlian()).toBe(false);
  });

  it('does not infer callback origin from an ordinary expiry or subsequent protocol hint', () => {
    const flow = new KunlianBrowserFlow();
    flow.observeFailure('SESSION_EXPIRED');
    flow.expectLocalProtocol();
    expect(flow.isCallbackEntry()).toBe(false);
    expect(flow.isKunlian()).toBe(true);
  });
});
