#!/usr/bin/env node
/**
 * Residual checker for docs-ui-refactor: after running normalize.cjs and doing
 * a manual pass, this flags half-width , ; : ? that still sit in a Chinese
 * context (including cases where markdown markup separates the punctuation from
 * the nearest CJK char). Reports file:line so a human can eyeball each hit.
 * Never edits.
 *
 * Usage: node scripts/detect.cjs <file...>
 * Note: 基础-文案规范.md legitimately keeps a few half-width marks (the ❌
 * counter-examples and the 西文半角 illustration) — those hits are expected.
 */
const fs = require('fs');
const CJK = /[㐀-䶿一-鿿豈-﫿]/;
const S = String.fromCharCode(1);

function mask(src) {
  let s = src;
  const put = () => S;
  s = s.replace(/```[\s\S]*?```/g, put);
  s = s.replace(/~~~[\s\S]*?~~~/g, put);
  s = s.replace(/<!--[\s\S]*?-->/g, put);
  s = s.replace(/^[ \t]*(?:import|export)[ \t][^\n]*$/gm, () => '');
  s = s.replace(/`[^`\n]*`/g, put);
  s = s.replace(/\[[^\]]*\]\([^)]*\)/g, put);        // whole [display](url)
  s = s.replace(/https?:\/\/[^\s)]+/g, put);
  s = s.replace(/[0-9A-Za-z一-鿿_./-]+\.(?:mdx?|tsx?|jsx?|cjs|mjs|css|json|svg|png|ya?ml|html?)\b/g, put);
  s = s.replace(/<\/?[A-Za-z][^>]*?>/g, put);
  return s;
}
// markup chars we "see through" when hunting for a CJK neighbour
const SKIP = new Set([' ', '\t', '*', '_', '~', '`', ')', ']', '(', '[',
  '（', '）', '【', '】', '「', '」', '『', '』', '"', '“', '”', "'", '《', '》', S, '#', '>', '-']);
const PUNCT = new Set([',', ';', ':', '?']);

function nearCJK(chars, i, dir) {
  let steps = 0;
  for (let j = i + dir; j >= 0 && j < chars.length && steps < 6; j += dir) {
    const c = chars[j];
    if (c === '\n' || c === '\r') return false;
    if (SKIP.has(c)) { steps++; continue; }
    return CJK.test(c);
  }
  return false;
}

let total = 0;
for (const f of process.argv.slice(2)) {
  mask(fs.readFileSync(f, 'utf8')).split('\n').forEach((line, idx) => {
    if (/^\s*\|?[\s:|-]+\|?\s*$/.test(line)) return; // table delimiter row
    const chars = Array.from(line);
    for (let i = 0; i < chars.length; i++) {
      if (!PUNCT.has(chars[i])) continue;
      if (chars[i] === ':' && /\d/.test(chars[i + 1] || '')) continue; // ratio/time
      if (nearCJK(chars, i, -1) || nearCJK(chars, i, +1)) {
        console.log(`${f}:${idx + 1}  [${chars[i]}]  ${line.trim().slice(0, 90)}`);
        total++;
        break; // one report per line is enough to eyeball
      }
    }
  });
}
console.log(`\n${total} line(s) flagged.`);
