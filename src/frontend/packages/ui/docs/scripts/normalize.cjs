#!/usr/bin/env node
/**
 * @bisheng/ui docs punctuation normalizer (all passes in one).
 *
 * Applies the 文案规范 / 文档撰写规范 rules to a doc's PROSE, leaving code,
 * JSX, links and URLs untouched:
 *   1. add a half-width space at CJK<->[A-Za-z0-9] boundaries
 *   2. half-width , ; : ? . -> full-width when in Chinese context
 *      (markup like ** ` ) is seen through, up to 2 hops)
 *   3. ASCII "..." pairs containing CJK -> 「」  (or “” with --curly)
 *   4. half-width ( ) in Chinese context -> （ ）, pair-aware
 *
 * SAFETY: 基础-文案规范.md is skipped by default — it contains deliberate
 * ❌ counter-examples (wrong-on-purpose text) that must NOT be normalized.
 * Edit that file by hand. Pass --force to override (you almost never should).
 *
 * Usage:
 *   node scripts/normalize.cjs [--curly] [--force] <file...>
 *   --curly  use full-width double quotes “” instead of 「」 (only 文案规范,
 *            which states the product quote standard, wants this)
 *
 * ALWAYS review the diff afterwards, then run detect.cjs to catch stragglers.
 */
const fs = require('fs');
const path = require('path');

const CJK = /[㐀-䶿一-鿿豈-﫿]/;
const S = String.fromCharCode(1);
const isCJK = (ch) => ch != null && CJK.test(ch);

function mask(src) {
  const store = [];
  const put = (m) => S + (store.push(m) - 1) + S;
  let s = src;
  s = s.replace(/```[\s\S]*?```/g, put);
  s = s.replace(/~~~[\s\S]*?~~~/g, put);
  s = s.replace(/<!--[\s\S]*?-->/g, put);
  s = s.replace(/^[ \t]*(?:import|export)[ \t][^\n]*$/gm, put);
  s = s.replace(/`[^`\n]*`/g, put);
  s = s.replace(/\[[^\]]*\]\([^)]*\)/g, put);     // whole [display](url) — filenames in link text must stay verbatim
  s = s.replace(/https?:\/\/[^\s)]+/g, put);
  // bare filename / path tokens (e.g. 组件-Button按钮.md, tailwind.config.cjs) —
  // identifiers, must stay verbatim (no CJK<->Latin spacing inside them)
  s = s.replace(/[0-9A-Za-z一-鿿_./-]+\.(?:mdx?|tsx?|jsx?|cjs|mjs|css|json|svg|png|ya?ml|html?)\b/g, put);
  s = s.replace(/<\/?[A-Za-z][^>]*?>/g, put);     // real tags only ("< 576px" is safe)
  return { s, store };
}
function unmask(s, store) {
  const re = new RegExp(S + '(\\d+)' + S, 'g');
  let prev;
  do { prev = s; s = s.replace(re, (_, i) => store[+i]); } while (s !== prev);
  return s;
}

function spacing(s) {
  s = s.replace(/([㐀-䶿一-鿿豈-﫿])([A-Za-z0-9])/g, '$1 $2');
  s = s.replace(/([A-Za-z0-9])([㐀-䶿一-鿿豈-﫿])/g, '$1 $2');
  return s;
}

const FULL = { ',': '，', ';': '；', ':': '：', '?': '？' };
const SKIP = new Set([' ', '\t', '*', '_', '~', ')', '(', '（', '）', '[', ']',
  '「', '」', '『', '』', '"', '“', '”', '《', '》', S]);

function nearCJK(chars, i, dir) {
  let skips = 0;
  for (let j = i + dir; j >= 0 && j < chars.length; j += dir) {
    const c = chars[j];
    if (c === '\n' || c === '\r') return false;
    if (SKIP.has(c)) { if (++skips > 2) return false; continue; }
    return isCJK(c);
  }
  return false;
}

function punct(line) {
  if (/^\s*\|?[\s:|-]+\|?\s*$/.test(line)) return line; // table delimiter row
  const chars = Array.from(line);
  const sideNS = (i, dir) => {
    for (let j = i + dir; j >= 0 && j < chars.length; j += dir) {
      if (chars[j] === ' ' || chars[j] === '\t') continue;
      return chars[j];
    }
    return null;
  };
  for (let i = 0; i < chars.length; i++) {
    const c = chars[i];
    if (c === '.') {
      const prev = sideNS(i, -1), next = sideNS(i, +1);
      if (isCJK(prev) && (next === null || isCJK(next))) chars[i] = '。';
    } else if (c in FULL) {
      if (c === ':' && /\d/.test(chars[i + 1] || '')) continue; // ratio/time 1:1
      if (nearCJK(chars, i, -1) || nearCJK(chars, i, +1)) chars[i] = FULL[c];
    }
  }
  return chars.join('');
}

function parens(line) {
  const chars = Array.from(line);
  const stack = [];
  const mark = new Set();
  for (let i = 0; i < chars.length; i++) {
    if (chars[i] === '(') stack.push(i);
    else if (chars[i] === ')' && stack.length) {
      const o = stack.pop();
      const inner = chars.slice(o + 1, i).join('');
      if (CJK.test(inner) || isCJK(chars[o - 1]) || isCJK(chars[i + 1])) { mark.add(o); mark.add(i); }
    }
  }
  if (!mark.size) return line;
  return chars.map((c, i) => (mark.has(i) ? (c === '(' ? '（' : '）') : c)).join('');
}

function quotes(line, open, close) {
  const chars = Array.from(line);
  const pos = [];
  for (let i = 0; i < chars.length; i++) if (chars[i] === '"') pos.push(i);
  for (let p = 0; p + 1 < pos.length; p += 2) {
    const a = pos[p], b = pos[p + 1];
    if (CJK.test(chars.slice(a + 1, b).join(''))) { chars[a] = open; chars[b] = close; }
  }
  return chars.join('');
}

function normalize(src, curly) {
  const { s, store } = mask(src);
  const [oq, cq] = curly ? ['“', '”'] : ['「', '」'];
  const out = spacing(s)
    .split('\n')
    .map((line) => punct(parens(quotes(line, oq, cq))))
    .join('\n');
  return unmask(out, store);
}

let curly = false, force = false;
const files = [];
for (const a of process.argv.slice(2)) {
  if (a === '--curly') curly = true;
  else if (a === '--force') force = true;
  else files.push(a);
}
let changed = 0;
for (const f of files) {
  if (path.basename(f) === '基础-文案规范.md' && !force) {
    console.log('  SKIP ', f, '(has ❌ counter-examples — edit by hand, or --force)');
    continue;
  }
  const src = fs.readFileSync(f, 'utf8');
  const out = normalize(src, curly);
  if (out !== src) { fs.writeFileSync(f, out); changed++; console.log('  fixed', f); }
  else console.log('  same ', f);
}
console.log('\n' + changed + ' file(s) changed. Review the diff, then run detect.cjs.');
