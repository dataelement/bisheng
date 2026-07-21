/**
 * rspack pre-loader for the docs site: strip internal working sections from
 * the spec markdown (docs-ui-refactor/*.md) BEFORE the MDX compiler sees the
 * source.
 *
 * Why a loader and not a remark plugin: rspress extracts the page TOC (and
 * search index) before user remarkPlugins run, so a remark-level strip left
 * ghost entries in the right-hand outline. Text-level stripping up front
 * keeps body / TOC / search consistent.
 *
 * The spec files are living working documents — migration ledgers, scan
 * archives, change logs and Claude-window handoff notes live next to the
 * reader-facing spec. The site's audience (PM / devs / new designers) should
 * only see the spec itself, while the md stays the single source of truth.
 *
 * Rules (see also docs-ui-refactor/00-总纲.md §五):
 * 1. A heading matching HEADING_PATTERNS is dropped together with everything
 *    until the next heading of the same or higher level.
 * 2. The blockquote directly below the document's first H1 is dropped — by
 *    convention it's working-doc meta (version stamp, 与总纲配套, notes to the
 *    next Claude window), not reader material.
 * 2b. Standalone `---` section separators are dropped entirely: the rspress
 *    theme already draws a divider before every h2, so the source separators
 *    render as doubled lines — and stripping sections leaves orphaned ones.
 * 3. Explicit markers for per-file curation:
 *      <!-- site-hide -->         hides the next heading's whole section
 *      <!-- site-hide:start -->   hides everything until
 *      <!-- site-hide:end -->
 */

const HEADING_PATTERNS = [
  /改动记录/, // change logs (every spec doc)
  /关键结论/, // “先读这个” digests addressed at incoming Claude windows
  /^附录/, // appendices (scan archives, usage ledgers)
  /^附[:：]/, // “附：已迁出本文的内容” style
  /落地记录/, // implementation logs
  /给实现窗口/, // sections addressed to the implementing Claude window
  /待决策清单/, // open-decision checklists for the designer
  /代码锚点/, // code anchor lists
  /扫描存档/, // scan archives outside 附录 headings
];

const HIDE_ONE = /^\s*<!--\s*site-hide\s*-->\s*$/;
const HIDE_START = /^\s*<!--\s*site-hide:start\s*-->\s*$/;
const HIDE_END = /^\s*<!--\s*site-hide:end\s*-->\s*$/;
const HEADING = /^(#{1,6})\s+(.+?)\s*$/;
const FENCE = /^\s*(```|~~~)/;

module.exports = function stripInternalSections(source) {
  const lines = source.split('\n');
  const out = [];
  let inFence = false;
  /** Depth of the heading whose section is being hidden, or null. */
  let sectionDepth = null;
  let inRange = false;
  let hideNextHeading = false;
  /** 'before-h1' → 'after-h1' (drop a leading meta blockquote) → 'done'. */
  let metaQuoteState = 'before-h1';

  for (const line of lines) {
    if (FENCE.test(line)) {
      // Fences inside hidden regions still toggle so a closing ``` inside a
      // hidden section doesn't leak fence state to the visible remainder.
      inFence = !inFence;
      if (sectionDepth === null && !inRange) out.push(line);
      continue;
    }
    if (inFence) {
      if (sectionDepth === null && !inRange) out.push(line);
      continue;
    }

    if (HIDE_START.test(line)) {
      inRange = true;
      continue;
    }
    if (HIDE_END.test(line)) {
      inRange = false;
      continue;
    }
    if (HIDE_ONE.test(line)) {
      hideNextHeading = true;
      continue;
    }
    if (inRange) continue;

    // Rule 2b: drop every standalone thematic break (see header).
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) continue;

    // Drop the meta blockquote that sits directly under the first H1.
    if (metaQuoteState === 'after-h1') {
      if (line.trim() === '') {
        out.push(line);
        continue;
      }
      if (line.trimStart().startsWith('>')) {
        continue; // swallow the whole leading blockquote
      }
      metaQuoteState = 'done'; // first real content — stop looking
    }

    const m = line.match(HEADING);
    if (m) {
      const depth = m[1].length;
      if (metaQuoteState === 'before-h1' && depth === 1) metaQuoteState = 'after-h1';
      if (sectionDepth !== null && depth <= sectionDepth) sectionDepth = null;
      const isInternal =
        hideNextHeading || HEADING_PATTERNS.some((p) => p.test(m[2]));
      hideNextHeading = false;
      if (sectionDepth === null && isInternal) {
        sectionDepth = depth;
        continue;
      }
      if (sectionDepth !== null) continue;
      out.push(line);
      continue;
    }

    if (sectionDepth !== null) continue;
    out.push(line);
  }

  return out.join('\n');
};
