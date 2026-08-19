#!/usr/bin/env node
/**
 * i18n consistency gate for the frontend workspace.
 *
 * Two checks, both ratcheted (existing debt is frozen in
 * scripts/i18n-baseline.json and may only shrink; anything NEW fails):
 *
 * 1. Key parity — every locale file must expose the same key set in every
 *    language (reference language: zh-Hans). Files in packages/locales are
 *    held to zero drift (no baseline): they were born clean.
 * 2. Error-code reconciliation — every backend error code declared in
 *    src/backend/bisheng/common/errcode must have copy in the shared
 *    api_errors domain, otherwise users see the backend's raw English Msg.
 *    (Frontend-only codes are reported as dead-key candidates, info only —
 *    they may belong to the commercial gateway.)
 * 3. Audit-action lockstep — the structured `namespace.entity.verb` actions the
 *    backend surfaces to the audit page must match the frontend filter list
 *    one-for-one, and each must have copy under `log.eventTypeEnum` in all
 *    three languages. Registered on one side only, an action is either written
 *    to the DB and unfindable, or offered in a filter that returns nothing
 *    forever. NOT ratcheted: this pair is clean as of 2026-08-19.
 *
 *   node scripts/check-i18n.mjs                    gate (CI + local)
 *   node scripts/check-i18n.mjs --update-baseline  re-freeze current state
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WS = path.dirname(path.dirname(fileURLToPath(import.meta.url))); // src/frontend
const BASELINE_FILE = path.join(WS, 'scripts', 'i18n-baseline.json');
const BACKEND_ERRCODE_DIR = path.resolve(WS, '..', 'backend', 'bisheng', 'common', 'errcode');
const BACKEND_AUDIT_FILE = path.resolve(WS, '..', 'backend', 'bisheng', 'database', 'models', 'audit_log.py');
const FRONTEND_LOG_API = path.join(WS, 'platform', 'src', 'controllers', 'API', 'log.ts');
const PLATFORM_BS_LOCALES = ['zh-Hans', 'en-US', 'ja'];

/** Where locale files live and which languages each scope must cover. */
const SCOPES = [
  {
    id: 'platform',
    base: 'zh-Hans',
    others: ['en-US', 'ja'],
    // one entry per namespace file found in the reference language
    files: () => fs.readdirSync(path.join(WS, 'platform/public/locales/zh-Hans')).filter((f) => f.endsWith('.json')),
    path: (lang, file) => path.join(WS, 'platform/public/locales', lang, file),
    ratcheted: true,
  },
  {
    id: 'client',
    base: 'zh-Hans',
    others: ['en', 'ja'],
    files: () => ['translation.json'],
    path: (lang, file) => path.join(WS, 'client/src/locales', lang, file),
    ratcheted: true,
  },
  {
    id: 'shared',
    base: 'zh-Hans',
    others: ['en', 'ja'],
    files: () => fs.readdirSync(path.join(WS, 'packages/locales/src')).map((domain) => `${domain}`),
    path: (lang, domain) => path.join(WS, 'packages/locales/src', domain, `${lang}.json`),
    ratcheted: false, // single source of truth stays perfectly aligned, always
  },
];

const flatten = (obj, prefix = '') =>
  Object.entries(obj).flatMap(([k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    return v !== null && typeof v === 'object' ? flatten(v, key) : [key];
  });

const readKeys = (file) => {
  if (!fs.existsSync(file)) return null;
  return new Set(flatten(JSON.parse(fs.readFileSync(file, 'utf8'))));
};

function collectParity() {
  const drift = {}; // "<scope>/<file>/<lang>" -> { missing: [], extra: [] }
  for (const scope of SCOPES) {
    for (const file of scope.files()) {
      const baseKeys = readKeys(scope.path(scope.base, file));
      if (!baseKeys) continue;
      for (const lang of scope.others) {
        const langKeys = readKeys(scope.path(lang, file));
        const missing = langKeys ? [...baseKeys].filter((k) => !langKeys.has(k)) : [...baseKeys];
        const extra = langKeys ? [...langKeys].filter((k) => !baseKeys.has(k)) : [];
        if (missing.length || extra.length) {
          drift[`${scope.id}/${file}/${lang}`] = { missing: missing.sort(), extra: extra.sort() };
        }
      }
    }
  }
  return drift;
}

function collectErrorCodes() {
  if (!fs.existsSync(BACKEND_ERRCODE_DIR)) {
    console.warn('[check-i18n] backend errcode dir not found — skipping reconciliation');
    return null;
  }
  const source = fs
    .readdirSync(BACKEND_ERRCODE_DIR)
    .filter((f) => f.endsWith('.py'))
    .map((f) => fs.readFileSync(path.join(BACKEND_ERRCODE_DIR, f), 'utf8'))
    .join('\n');
  const backend = new Set([...source.matchAll(/Code:\s*int\s*=\s*(\d+)/g)].map((m) => m[1]));
  const frontend = readKeys(path.join(WS, 'packages/locales/src/api_errors/zh-Hans.json'));
  return {
    missingCopy: [...backend].filter((c) => !frontend.has(c)).sort(),
    frontendOnly: [...frontend].filter((k) => /^\d+$/.test(k) && !backend.has(k)).sort(),
  };
}

/**
 * Fold a structured action into its `log.eventTypeEnum` key.
 *
 * Must stay identical to `actionToI18nKey` in
 * platform/src/controllers/API/log.ts — that function is what both the filter
 * dropdown label and the audit table cell go through, so this reimplementation
 * is the thing being checked, not a convenience.
 */
const foldActionKey = (action) => {
  const [head, ...rest] = action.split(/[._]/).filter(Boolean);
  if (!head) return action;
  return head + rest.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join('');
};

/** Text between `marker` and the first line that is exactly `end`. */
const sliceBlock = (source, marker, end) => {
  const i = source.indexOf(marker);
  if (i < 0) return null;
  const j = source.indexOf(end, i);
  return j < 0 ? null : source.slice(i, j);
};

function collectAuditActions() {
  if (!fs.existsSync(BACKEND_AUDIT_FILE) || !fs.existsSync(FRONTEND_LOG_API)) {
    console.warn('[check-i18n] audit action source not found — skipping lockstep check');
    return null;
  }
  const py = fs.readFileSync(BACKEND_AUDIT_FILE, 'utf8');
  const ts = fs.readFileSync(FRONTEND_LOG_API, 'utf8');

  const pyBlock = sliceBlock(py, '_UI_VISIBLE_V2_ACTIONS', '\n)');
  const tsBlock = sliceBlock(ts, 'export const V2_ACTIONS', '\n];');
  if (pyBlock === null || tsBlock === null) {
    // The declaration was renamed or reshaped. Failing loudly beats silently
    // checking nothing — a green gate that stopped looking is worse than none.
    return { unparsable: true, backendOnly: [], frontendOnly: [], missingCopy: [], missingNamespace: [] };
  }
  const backend = [...pyBlock.matchAll(/^\s+"([a-z0-9_.]+)",\s*$/gm)].map((m) => m[1]);
  const frontend = [...tsBlock.matchAll(/^\s+'([a-z0-9_.]+)',\s*$/gm)].map((m) => m[1]);

  const nsBlock = sliceBlock(py, '_V2_NAMESPACE_TO_ACTION_PREFIX', '\n}') ?? '';
  const namespaces = [...nsBlock.matchAll(/^\s+"([a-z_]+)":/gm)].map((m) => m[1]);

  const locales = PLATFORM_BS_LOCALES.map((lang) => {
    const file = path.join(WS, 'platform', 'public', 'locales', lang, 'bs.json');
    const log = fs.existsSync(file) ? (JSON.parse(fs.readFileSync(file, 'utf8')).log ?? {}) : {};
    return { lang, eventType: log.eventTypeEnum ?? {}, systemId: log.systemIdEnum ?? {} };
  });

  const missingCopy = [];
  for (const action of backend) {
    const key = foldActionKey(action);
    for (const { lang, eventType } of locales) {
      if (!(key in eventType)) missingCopy.push(`${lang}:log.eventTypeEnum.${key} (${action})`);
    }
  }
  const missingNamespace = [];
  for (const ns of namespaces) {
    for (const { lang, systemId } of locales) {
      // renderSystemId falls back to the action's first segment for v2 rows, so
      // the bare namespace needs an entry of its own — the camelCase dropdown
      // key (`openApi`, `appFactory`) is a different lookup.
      if (!(ns in systemId)) missingNamespace.push(`${lang}:log.systemIdEnum.${ns}`);
    }
  }

  return {
    unparsable: false,
    backendOnly: backend.filter((a) => !frontend.includes(a)),
    frontendOnly: frontend.filter((a) => !backend.includes(a)),
    missingCopy,
    missingNamespace,
  };
}

// ---------------------------------------------------------------------------

const drift = collectParity();
const codes = collectErrorCodes();
const auditActions = collectAuditActions();

if (process.argv.includes('--update-baseline')) {
  const baseline = { parity: drift, errorCodes: { missingCopy: codes?.missingCopy ?? [] } };
  fs.writeFileSync(BASELINE_FILE, JSON.stringify(baseline, null, 2) + '\n');
  console.log(`[check-i18n] baseline rewritten: ${path.relative(WS, BASELINE_FILE)}`);
  process.exit(0);
}

const baseline = fs.existsSync(BASELINE_FILE)
  ? JSON.parse(fs.readFileSync(BASELINE_FILE, 'utf8'))
  : { parity: {}, errorCodes: { missingCopy: [] } };

const problems = [];

// 1. Parity: new drift fails; drift that healed must be pruned from baseline.
const allSlots = new Set([...Object.keys(drift), ...Object.keys(baseline.parity)]);
for (const slot of allSlots) {
  const ratcheted = SCOPES.find((s) => slot.startsWith(`${s.id}/`))?.ratcheted ?? true;
  const now = drift[slot] ?? { missing: [], extra: [] };
  const frozen = (ratcheted && baseline.parity[slot]) || { missing: [], extra: [] };
  for (const kind of ['missing', 'extra']) {
    const fresh = now[kind].filter((k) => !frozen[kind].includes(k));
    const healed = frozen[kind].filter((k) => !now[kind].includes(k));
    if (fresh.length) {
      problems.push(`${slot}: ${fresh.length} NEW ${kind} key(s): ${fresh.slice(0, 10).join(', ')}${fresh.length > 10 ? ' …' : ''}`);
    }
    if (healed.length) {
      problems.push(`${slot}: ${healed.length} ${kind} key(s) healed — shrink the baseline with --update-baseline`);
    }
  }
}

// 2. Error codes: a new backend code without copy fails.
if (codes) {
  const frozen = baseline.errorCodes?.missingCopy ?? [];
  const fresh = codes.missingCopy.filter((c) => !frozen.includes(c));
  const healed = frozen.filter((c) => !codes.missingCopy.includes(c));
  if (fresh.length) {
    problems.push(`api_errors: ${fresh.length} NEW backend code(s) without frontend copy: ${fresh.join(', ')} — add all three languages in packages/locales/src/api_errors/`);
  }
  if (healed.length) {
    problems.push(`api_errors: ${healed.length} code(s) gained copy — shrink the baseline with --update-baseline`);
  }
  if (codes.frontendOnly.length) {
    console.log(`[check-i18n] info: ${codes.frontendOnly.length} frontend-only error code(s) (dead-key candidates / gateway codes)`);
  }
}

// 3. Audit actions: the backend whitelist and the frontend filter are one list
//    kept in two places. Not ratcheted — it is clean, and it must stay clean.
if (auditActions) {
  if (auditActions.unparsable) {
    problems.push('audit actions: could not parse _UI_VISIBLE_V2_ACTIONS / V2_ACTIONS — the declaration moved; fix scripts/check-i18n.mjs rather than dropping the check');
  }
  if (auditActions.backendOnly.length) {
    problems.push(`audit actions: ${auditActions.backendOnly.length} backend action(s) missing from the platform filter: ${auditActions.backendOnly.join(', ')} — add to V2_ACTIONS in platform/src/controllers/API/log.ts, else the event is written and unfindable`);
  }
  if (auditActions.frontendOnly.length) {
    problems.push(`audit actions: ${auditActions.frontendOnly.length} filter action(s) the backend never surfaces: ${auditActions.frontendOnly.join(', ')} — add to _UI_VISIBLE_V2_ACTIONS in audit_log.py, else the filter returns nothing forever`);
  }
  if (auditActions.missingCopy.length) {
    problems.push(`audit actions: ${auditActions.missingCopy.length} missing log.eventTypeEnum entry/entries: ${auditActions.missingCopy.slice(0, 8).join(', ')}${auditActions.missingCopy.length > 8 ? ' …' : ''} — the audit table renders the raw action string without them`);
  }
  if (auditActions.missingNamespace.length) {
    problems.push(`audit actions: ${auditActions.missingNamespace.length} missing log.systemIdEnum entry/entries: ${auditActions.missingNamespace.join(', ')} — the module column renders the raw namespace without them`);
  }
}

if (problems.length) {
  console.error(`[check-i18n] FAILED — ${problems.length} problem(s):`);
  for (const p of problems) console.error(`  - ${p}`);
  console.error('[check-i18n] rule: new keys ship zh-Hans/en/ja together; frozen legacy drift may only shrink.');
  process.exit(1);
}
console.log('[check-i18n] OK — no new i18n drift');
