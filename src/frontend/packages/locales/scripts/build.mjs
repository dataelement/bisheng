#!/usr/bin/env node
/**
 * Compiles the shared copy source (src/<domain>/<lang>.json) into the locale
 * artifacts each app actually loads at runtime. The apps' i18n runtimes stay
 * untouched — only where the copy comes from changes.
 *
 *   node scripts/build.mjs           write artifacts (only when content changed)
 *   node scripts/build.mjs --check   fail (exit 1) if artifacts are stale — CI gate
 *   node scripts/build.mjs --watch   rebuild on every source change — dev loop
 *
 * Artifacts are committed to git; never edit them by hand.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const PKG_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const WORKSPACE = path.resolve(PKG_ROOT, '..', '..');
const SRC_DIR = path.join(PKG_ROOT, 'src');

// Platform ships language dirs named after full locale tags; client uses short ones.
const PLATFORM_LANG = { 'zh-Hans': 'zh-Hans', en: 'en-US', ja: 'ja' };

/**
 * One entry per (domain × app). `emit` receives the parsed source for a
 * language and returns the artifact's absolute path plus its JSON content.
 */
const TARGETS = [
  {
    domain: 'api_errors',
    app: 'platform',
    emit: (lang, data) => ({
      file: path.join(WORKSPACE, 'platform', 'public', 'locales', PLATFORM_LANG[lang], 'api_errors.json'),
      content: data, // standalone lazy-loaded i18next namespace, flat <code>: copy
    }),
  },
  {
    domain: 'api_errors',
    app: 'client',
    emit: (lang, data) => ({
      file: path.join(WORKSPACE, 'client', 'src', 'locales', lang, 'api_errors.gen.json'),
      content: data, // merged under the translation resource by locales/i18n.ts
    }),
  },
  {
    domain: 'shared',
    app: 'platform',
    emit: (lang, data) => ({
      file: path.join(WORKSPACE, 'platform', 'public', 'locales', PLATFORM_LANG[lang], 'shared.json'),
      content: data, // lazy i18next namespace, addressed as shared:<key>
    }),
  },
  {
    domain: 'shared',
    app: 'client',
    emit: (lang, data) => ({
      file: path.join(WORKSPACE, 'client', 'src', 'locales', lang, 'shared.gen.json'),
      content: data, // registered as the 'shared' namespace by locales/i18n.ts
    }),
  },
];

function readSource(domain, lang) {
  const file = path.join(SRC_DIR, domain, `${lang}.json`);
  if (!fs.existsSync(file)) {
    console.error(`[locales] missing source file: ${path.relative(WORKSPACE, file)}`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function languagesOf(domain) {
  return fs
    .readdirSync(path.join(SRC_DIR, domain))
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.replace(/\.json$/, ''));
}

function compile({ checkOnly }) {
  const stale = [];
  let written = 0;
  for (const target of TARGETS) {
    for (const lang of languagesOf(target.domain)) {
      const { file, content } = target.emit(lang, readSource(target.domain, lang));
      const next = JSON.stringify(content, null, 2) + '\n';
      const current = fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
      if (current === next) continue;
      if (checkOnly) {
        stale.push(path.relative(WORKSPACE, file));
      } else {
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, next);
        written++;
        console.log(`[locales] wrote ${path.relative(WORKSPACE, file)}`);
      }
    }
  }
  if (checkOnly && stale.length > 0) {
    console.error(
      `[locales] ${stale.length} artifact(s) out of sync with packages/locales/src ` +
        `(edit the source, never the artifact, then run \`pnpm --filter @bisheng/locales build\`):`,
    );
    for (const f of stale) console.error(`  - ${f}`);
    process.exit(1);
  }
  if (!checkOnly && written === 0) console.log('[locales] artifacts already up to date');
}

const args = process.argv.slice(2);
compile({ checkOnly: args.includes('--check') });

if (args.includes('--watch')) {
  console.log(`[locales] watching ${path.relative(WORKSPACE, SRC_DIR)} …`);
  let timer = null;
  fs.watch(SRC_DIR, { recursive: true }, () => {
    // Editors fire bursts of events per save; collapse them into one rebuild.
    clearTimeout(timer);
    timer = setTimeout(() => compile({ checkOnly: false }), 150);
  });
}
