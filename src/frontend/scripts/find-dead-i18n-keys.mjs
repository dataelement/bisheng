#!/usr/bin/env node
/**
 * Dead i18n key scanner.
 *
 * For every key in the app locale files, looks for the full key string
 * anywhere in that app's source. Keys under a dynamically-composed prefix
 * (t(`xxx${...}`) and friends) are NEVER touched — they cannot be judged
 * statically. Remaining unreferenced keys are split into:
 *
 *   safe        — full key absent AND its last segment appears nowhere either
 *   needsReview — full key absent, but the leaf segment shows up somewhere
 *                 (could be composed in an unusual way; delete only after a
 *                 human look)
 *
 *   node scripts/find-dead-i18n-keys.mjs                       scan + report
 *   node scripts/find-dead-i18n-keys.mjs --delete --scope client --prefix com_
 *                 delete SAFE candidates matching --prefix from every language
 *                 of the scope (always rerun the scan first; then run the app
 *                 build + check-i18n --update-baseline)
 *
 * Report: scripts/i18n-dead-keys-report.json
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const WS = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const REPORT_FILE = path.join(WS, 'scripts', 'i18n-dead-keys-report.json');

const SCOPES = [
  {
    id: 'platform',
    srcDirs: ['platform/src'],
    langs: ['zh-Hans', 'en-US', 'ja'],
    // api_errors is generated + reconciled against the backend registry by check-i18n
    files: () => fs.readdirSync(path.join(WS, 'platform/public/locales/zh-Hans')).filter((f) => f.endsWith('.json') && f !== 'api_errors.json'),
    path: (lang, file) => path.join(WS, 'platform/public/locales', lang, file),
    // platform addresses keys as "key" (default ns), "ns:key", or t('key', {ns})
    nsOf: (file) => file.replace(/\.json$/, ''),
  },
  {
    id: 'client',
    srcDirs: ['client/src'],
    langs: ['zh-Hans', 'en', 'ja'],
    files: () => ['translation.json'],
    path: (lang, file) => path.join(WS, 'client/src/locales', lang, file),
    nsOf: () => null,
  },
];

const SRC_EXT = new Set(['.ts', '.tsx', '.js', '.jsx']);

function* walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === 'locales') continue;
      yield* walk(p);
    } else if (SRC_EXT.has(path.extname(e.name))) {
      yield p;
    }
  }
}

const flatten = (obj, prefix = '') =>
  Object.entries(obj).flatMap(([k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    return v !== null && typeof v === 'object' ? flatten(v, key) : [key];
  });

/** Static prefixes of dynamically composed keys: `xxx${…}`, 'xxx' + …, "xxx".concat */
function dynamicPrefixes(source) {
  const prefixes = new Set();
  for (const m of source.matchAll(/`([\w.:\-\/ ]*?)\$\{/g)) if (m[1]) prefixes.add(m[1]);
  for (const m of source.matchAll(/['"]([\w.:\-\/ ]+?)['"]\s*\+/g)) if (m[1]) prefixes.add(m[1]);
  return prefixes;
}

function scanScope(scope) {
  let source = '';
  for (const dir of scope.srcDirs) for (const f of walk(path.join(WS, dir))) source += fs.readFileSync(f, 'utf8') + '\n';
  const dynPrefixes = [...dynamicPrefixes(source)];
  const isDynamic = (addr) => dynPrefixes.some((p) => p.length >= 3 && addr.startsWith(p));

  // Locale values can reference other keys via $t(key) / $t(ns:key) nesting —
  // those keys are alive even when no source file names them.
  const nestedRefs = new Set();
  for (const file of scope.files()) {
    for (const lang of scope.langs) {
      const f = scope.path(lang, file);
      if (!fs.existsSync(f)) continue;
      for (const m of fs.readFileSync(f, 'utf8').matchAll(/\$t\(([^),]+)/g)) nestedRefs.add(m[1].trim());
    }
  }

  const result = {};
  for (const file of scope.files()) {
    const ns = scope.nsOf(file);
    const keys = flatten(JSON.parse(fs.readFileSync(scope.path(scope.langs[0], file), 'utf8')));
    const groups = { referenced: 0, dynamic: [], safe: [], needsReview: [] };
    for (const key of keys) {
      // every way this key can be addressed in code
      const addrs = ns ? [key, `${ns}:${key}`] : [key];
      if (addrs.some(isDynamic)) {
        groups.dynamic.push(key);
      } else if (addrs.some((a) => source.includes(a) || nestedRefs.has(a))) {
        groups.referenced++;
      } else {
        const leaf = key.split('.').pop();
        (leaf.length >= 3 && source.includes(leaf) ? groups.needsReview : groups.safe).push(key);
      }
    }
    result[file] = { total: keys.length, ...groups };
  }
  return result;
}

// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const report = {};
for (const scope of SCOPES) report[scope.id] = scanScope(scope);
fs.writeFileSync(REPORT_FILE, JSON.stringify(report, null, 2) + '\n');

console.log('scope/file                     total   used  dynamic  safe-dead  needs-review');
for (const [scopeId, files] of Object.entries(report)) {
  for (const [file, g] of Object.entries(files)) {
    console.log(
      `${(scopeId + '/' + file).padEnd(30)} ${String(g.total).padStart(5)} ${String(g.referenced).padStart(6)} ${String(g.dynamic.length).padStart(8)} ${String(g.safe.length).padStart(10)} ${String(g.needsReview.length).padStart(13)}`,
    );
  }
}
console.log(`\nreport: ${path.relative(WS, REPORT_FILE)}`);

if (args.includes('--delete')) {
  const scopeId = args[args.indexOf('--scope') + 1];
  const prefix = args.includes('--prefix') ? args[args.indexOf('--prefix') + 1] : '';
  const scope = SCOPES.find((s) => s.id === scopeId);
  if (!scope) {
    console.error(`--delete requires --scope <${SCOPES.map((s) => s.id).join('|')}>`);
    process.exit(1);
  }
  for (const [file, g] of Object.entries(report[scopeId])) {
    const doomed = g.safe.filter((k) => k.startsWith(prefix));
    if (!doomed.length) continue;
    for (const lang of scope.langs) {
      const f = scope.path(lang, file);
      if (!fs.existsSync(f)) continue;
      const j = JSON.parse(fs.readFileSync(f, 'utf8'));
      for (const key of doomed) {
        // delete nested path
        const parts = key.split('.');
        let node = j;
        for (const p of parts.slice(0, -1)) node = node?.[p];
        if (node) delete node[parts.at(-1)];
      }
      fs.writeFileSync(f, JSON.stringify(j, null, 2) + '\n');
    }
    console.log(`[deleted] ${scopeId}/${file}: ${doomed.length} safe key(s)${prefix ? ` with prefix "${prefix}"` : ''} from all languages`);
  }
  console.log('now run: app builds + node scripts/check-i18n.mjs --update-baseline');
}
