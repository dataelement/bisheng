import { safeKunlianReturnTo } from './kunlianBrowser';

export type KunlianWorkflowEntry = {
  kind: 'edit' | 'run';
  workflowId: string;
  chatId?: string;
  returnTo: string;
  failureCode?: number;
};

export type KunlianWorkflowEntryResult = KunlianWorkflowEntry
  | { kind: 'not-entry' }
  | { kind: 'invalid-entry' };

export type KunlianWorkflowEntryStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export type KunlianWorkflowAttemptOptions = {
  storage?: KunlianWorkflowEntryStorage | null;
  now?: number;
  manual?: boolean;
  callback?: boolean;
};

type LoginAttempt = Pick<KunlianWorkflowEntry, 'kind' | 'workflowId' | 'returnTo'> & { startedAt: number };

export const KUNLIAN_WORKFLOW_ATTEMPT_KEY = 'kunlian:workflow-entry-attempt';
export const KUNLIAN_WORKFLOW_ATTEMPT_TTL_MS = 10 * 60 * 1000;
const WORKFLOW_ID = /^[0-9a-f]{32}$/;
const FAILURE_CODE = /^1932[0-9]$/;

function assertId(id: string): void {
  if (!WORKFLOW_ID.test(id)) throw new Error('KUNLIAN_WORKFLOW_ENTRY_INVALID');
}

export function buildKunlianWorkflowEditPath(workflowId: string): string {
  assertId(workflowId);
  return `/flow/${workflowId}?from=workflow-management&entry=kunlian`;
}

export function buildKunlianWorkflowRunPath(workflowId: string, chatId?: string): string {
  assertId(workflowId);
  if (chatId !== undefined) assertId(chatId);
  return `/workspace/app/${chatId === undefined ? '' : `${chatId}/`}${workflowId}/10?entry=kunlian`;
}

/** Accept the browser pathname + search before URL normalization can hide unsafe paths. */
export function parseKunlianWorkflowEntry(raw: string): KunlianWorkflowEntryResult {
  const queryAt = raw.indexOf('?');
  const query = new URLSearchParams(queryAt < 0 ? '' : raw.slice(queryAt + 1).split('#')[0]);
  // Other entry markers, such as entry=explore, retain their existing behavior.
  const candidate = Array.from(query).some(([key, value]) =>
    key.toLowerCase() === 'entry' && value.toLowerCase().includes('kunlian'));
  if (!candidate) return { kind: 'not-entry' };
  const invalid = { kind: 'invalid-entry' } as const;
  if (raw.length > 2048 || safeKunlianReturnTo(raw) !== raw) return invalid;
  try {
    decodeURIComponent(raw);
  } catch {
    return invalid;
  }

  const pathname = raw.slice(0, queryAt);
  const edit = /^\/flow\/([0-9a-f]{32})\/?$/.exec(pathname);
  const run = /^\/workspace\/app\/(?:([0-9a-f]{32})\/)?([0-9a-f]{32})\/10\/?$/.exec(pathname);
  if (!edit && !run) return invalid;
  const allowed = new Set(edit ? ['from', 'entry', 'status_code'] : ['entry', 'status_code']);
  const seen = new Set<string>();
  for (const [key] of query) {
    if (!allowed.has(key) || seen.has(key)) return invalid;
    seen.add(key);
  }
  if (query.get('entry') !== 'kunlian' || (edit && query.get('from') !== 'workflow-management')) return invalid;
  const failure = query.get('status_code');
  if (failure !== null && !FAILURE_CODE.test(failure)) return invalid;
  const failed = failure === null ? {} : { failureCode: Number(failure) };
  if (edit) {
    const workflowId = edit[1];
    return { kind: 'edit', workflowId, returnTo: buildKunlianWorkflowEditPath(workflowId), ...failed };
  }
  const [, chatId, workflowId] = run!;
  return {
    kind: 'run', workflowId, ...(chatId === undefined ? {} : { chatId }),
    returnTo: buildKunlianWorkflowRunPath(workflowId, chatId), ...failed,
  };
}

function validatedEntry(entry: KunlianWorkflowEntry): KunlianWorkflowEntry | null {
  const parsed = parseKunlianWorkflowEntry(entry.returnTo);
  if ((parsed.kind !== 'edit' && parsed.kind !== 'run') || parsed.kind !== entry.kind
      || parsed.workflowId !== entry.workflowId || parsed.chatId !== entry.chatId
      || (entry.failureCode !== undefined && !FAILURE_CODE.test(String(entry.failureCode)))) return null;
  return { ...parsed, ...(entry.failureCode === undefined ? {} : { failureCode: entry.failureCode }) };
}

function resolveStorage(storage?: KunlianWorkflowEntryStorage | null): KunlianWorkflowEntryStorage | null {
  try {
    return storage === undefined ? sessionStorage : storage;
  } catch {
    return null;
  }
}

function readAttempt(raw: string | null): LoginAttempt | null {
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
    const item = value as Record<string, unknown>;
    if (Object.keys(item).length !== 4 || (item.kind !== 'edit' && item.kind !== 'run')
        || typeof item.workflowId !== 'string' || typeof item.returnTo !== 'string'
        || typeof item.startedAt !== 'number' || !Number.isSafeInteger(item.startedAt)
        || item.startedAt < 0) return null;
    const target = parseKunlianWorkflowEntry(item.returnTo);
    if ((target.kind !== 'edit' && target.kind !== 'run') || target.kind !== item.kind
        || target.workflowId !== item.workflowId || target.returnTo !== item.returnTo
        || target.failureCode !== undefined) return null;
    return { kind: target.kind, workflowId: target.workflowId, returnTo: target.returnTo, startedAt: item.startedAt };
  } catch {
    return null;
  }
}

/** Claim navigation only; this performs no request and grants no authenticated identity. */
export function claimKunlianWorkflowLoginAttempt(
  entry: KunlianWorkflowEntry,
  options: KunlianWorkflowAttemptOptions = {},
): boolean {
  const target = validatedEntry(entry);
  const now = options.now ?? Date.now();
  const manual = options.manual === true;
  if (!target || !Number.isSafeInteger(now) || now < 0) return false;
  if (!manual && (options.callback !== false || target.failureCode !== undefined)) return false;
  const storage = resolveStorage(options.storage);
  if (!storage) return manual;
  try {
    const raw = storage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY);
    const previous = readAttempt(raw);
    // Corrupt or future-dated marks require explicit recovery, rather than another automatic redirect.
    if (!manual && raw !== null && (!previous || previous.startedAt > now)) return false;
    // The conversation path may change, but automatic login for this workflow stays deduplicated.
    if (!manual && previous?.kind === target.kind && previous.workflowId === target.workflowId
        && now - previous.startedAt < KUNLIAN_WORKFLOW_ATTEMPT_TTL_MS) return false;
    const attempt: LoginAttempt = {
      kind: target.kind, workflowId: target.workflowId, returnTo: target.returnTo, startedAt: now,
    };
    const serialized = JSON.stringify(attempt);
    storage.setItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY, serialized);
    return manual || storage.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY) === serialized;
  } catch {
    // Without a persisted deduplication mark, only explicit manual navigation is permitted.
    return manual;
  }
}

export function clearKunlianWorkflowLoginAttempt(
  entry: KunlianWorkflowEntry,
  storage?: KunlianWorkflowEntryStorage | null,
): boolean {
  const target = validatedEntry(entry);
  if (!target) return false;
  const store = resolveStorage(storage);
  if (!store) return false;
  try {
    const previous = readAttempt(store.getItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY));
    // A chat redirect keeps the same workflow/action; another workflow or action must remain intact.
    if (!previous || previous.kind !== target.kind || previous.workflowId !== target.workflowId) return false;
    store.removeItem(KUNLIAN_WORKFLOW_ATTEMPT_KEY);
    return true;
  } catch {
    return false;
  }
}
