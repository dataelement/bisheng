import type { ChatCitation } from './types';
import { CITATION_START, CITATION_SEPARATOR, CITATION_END, normalizeCitationMarkers, buildCitationDisplayData } from './markers';
interface ExportUtilities {
  normalizeCitationType: (type?: string) => string;
  getCitationDocumentName: (detail?: ChatCitation | null) => string;
  getCitationItem: (detail: ChatCitation | null, id?: string) => import('./types').ChatCitationItem | null;
  formatCitationLocation: (detail: ChatCitation | null, id?: string) => string;
}
export function createExportUtilities({normalizeCitationType,getCitationDocumentName,getCitationItem,formatCitationLocation}: ExportUtilities) {
function stripCitationMarkers(content: string) {
  if (!content) return content;
  return content
    // Strip well-formed groups first (non-greedy across separators).
    .replace(/[\s\S]*?/g, '')
    // Also handle the escaped form ("...") that may slip through
    // when a message hasn't been passed through normalizeCitationMarkers.
    .replace(/\\u[eE]200[\s\S]*?\\u[eE]202/g, '')
    // Drop any orphan markers (e.g. a streaming-truncated group).
    .replace(/[]/g, '');
}

// Short citation handles the task-mode model writes as `[S3]` (F069). The
// grammar mirrors the backend's citation_handle_service (_RUN_RE / _DEF_LINE_RE
// / _CODE_RE) so that what the writer leaves literal and what an export drops
// agree: one handle is `S` + 1-4 digits; a group is one or more handles in
// brackets separated by `,` / U+FF0C / U+3001; a run is one or more adjacent
// groups. A run is never the label of a markdown link (`[S3](url)`), never
// glued to an ASCII identifier character or another `[`, and never inside
// code. The lookbehind is ASCII-only on purpose (mirrors the backend
// `_RUN_RE`): a handle glued to a CJK word is the common case, not an
// identifier.
const CITATION_HANDLE = 'S\\d{1,4}';
const CITATION_HANDLE_GROUP = `\\[\\s*${CITATION_HANDLE}(?:\\s*[,\uff0c\u3001]\\s*${CITATION_HANDLE})*\\s*\\]`;
const CITATION_HANDLE_RUN_RE = new RegExp(
  `(?<![A-Za-z0-9_\\[])${CITATION_HANDLE_GROUP}(?:\\s*${CITATION_HANDLE_GROUP})*(?!\\s*\\()`,
  'gu',
);
// `[S3]: some source` - a definition line the model wrote on its own; kept as is.
const CITATION_HANDLE_DEF_LINE_RE = new RegExp(`^[ \\t]*${CITATION_HANDLE_GROUP}[ \\t]*[:\uff1a]`, 'gmu');
// Fenced blocks and inline code spans are never rewritten.
const CITATION_CODE_RE = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;
const defLinePlaceholder = (index: number) => `\u0000DEF${index}\u0000`;

function stripHandleRunsOutsideDefinitions(segment: string) {
  const stash: string[] = [];
  const protectedSegment = segment.replace(CITATION_HANDLE_DEF_LINE_RE, (line) => {
    stash.push(line);
    return defLinePlaceholder(stash.length - 1);
  });
  let stripped = protectedSegment.replace(CITATION_HANDLE_RUN_RE, '');
  stash.forEach((line, index) => {
    stripped = stripped.replace(defLinePlaceholder(index), line);
  });
  return stripped;
}

/**
 * Remove every unresolved short-handle run (`[S3]`, `[S3][S7]`, `[S3, S7]`)
 * from a string. Used on the save-as-markdown path (download / knowledge-space
 * save) after stripCitationMarkers: a handle the backend could not resolve
 * stays literal in the file the model wrote, and a saved file must not leak
 * it. Code spans, fenced blocks, link labels and `[Sn]:` definition lines are
 * left untouched, exactly as the backend's strip_citation_handles does.
 */
function stripCitationHandles(content: string) {
  if (!content || !content.includes('[')) return content;
  const out: string[] = [];
  let last = 0;
  for (const match of content.matchAll(CITATION_CODE_RE)) {
    const start = match.index ?? 0;
    if (start > last) out.push(stripHandleRunsOutsideDefinitions(content.slice(last, start)));
    out.push(match[0]);
    last = start + match[0].length;
  }
  if (last < content.length) out.push(stripHandleRunsOutsideDefinitions(content.slice(last)));
  return out.join('');
}

// ---------------------------------------------------------------------------
// F069 P2: export baking (design decision 8, spec AC-20 / AC-22 / AC-24).
//
// A saved / downloaded markdown must not carry the private-use citation spans
// the preview turns into badges (they wrap bare internal ids), but the reader
// still deserves the sources. So the export bakes each span into a visible
// `[n]` numbered by first appearance and appends a reference list. Numbering
// follows the badge rule in transformPrivateCitations (one number per
// `${type}_${groupKey}_${itemId}`) so the file agrees with what the preview
// showed. A ref whose detail the caller could not obtain is dropped rather
// than numbered: a number without a list entry would be a dangling pointer,
// and a raw id must never reach the file (AC-24). Unresolved short handles
// (`[S99]`) go the way stripCitationHandles sends them (AC-19).
// ---------------------------------------------------------------------------

const CITATION_SPAN_RE = new RegExp(`${CITATION_START}([^${CITATION_START}${CITATION_END}]*)${CITATION_END}`, 'g');
const CITATION_STRAY_MARKER_RE = new RegExp(`[${CITATION_START}${CITATION_SEPARATOR}${CITATION_END}]`, 'g');
const EXPORT_PART_SEPARATOR = ' · ';

type BakedCitationEntry = {
  label: number;
  detail: ChatCitation;
  itemId: string;
};

function joinExportParts(parts: Array<string | undefined | null>) {
  const seen = new Set<string>();
  const cleaned: string[] = [];
  for (const part of parts) {
    const value = String(part ?? '').trim();
    // Empty parts are omitted; an exact repeat (a web title that fell back to
    // the url) would print the same text twice on one line.
    if (!value || seen.has(value)) continue;
    seen.add(value);
    cleaned.push(value);
  }
  return cleaned.join(EXPORT_PART_SEPARATOR);
}

/**
 * Where a cited chunk sits in its file: "第 N 页" when it has a real page,
 * else "第 N 段". Two page conventions reach here. Chunks parsed with a layout
 * (PDF, and office files converted to PDF) carry bboxes, and their page is the
 * zero-based index the bboxes use — the first page is 0 (PdfViewer adds 1 the
 * same way). Chunks without a layout carry a one-based page (slides) or 0 for
 * "not paginated" (docx / xlsx / md). The chunk index is zero-based too.
 * Mirrors the backend export (citation_handle_service._location_label).
 */
/** One reference-list line. Same shape the backend export renders. */
function formatCitationExportLine(entry: BakedCitationEntry) {
  const { detail, itemId } = entry;
  const payload = detail.sourcePayload;
  const type = normalizeCitationType(detail.type);
  if (type === 'web') {
    const item = getCitationItem(detail, itemId);
    const url = payload?.url || payload?.sourceUrl || '';
    return joinExportParts([item?.title || payload?.title || url, payload?.source, url]);
  }
  if (type === 'article') {
    return joinExportParts([payload?.title, payload?.sourceUrl]);
  }
  return joinExportParts([
    `《${getCitationDocumentName(detail)}》`,
    formatCitationLocation(detail, itemId),
    payload?.knowledgeName,
  ]);
}

/**
 * Bake private-use citation spans into visible `[n]` markers and append a
 * reference list under `heading`.
 *
 * Pure: `details` is everything the caller managed to resolve (the run's
 * `output_result.citations` seed plus whatever the preview already fetched);
 * this function neither fetches nor caches. A span whose refs all lack a
 * detail is removed entirely; a span that mixes resolved and unresolved refs
 * keeps only the resolved numbers. Code fences and inline code are left as
 * they are. Running it on already-baked text is a no-op apart from the
 * unresolved-handle stripping, so a double export cannot double the list.
 */
function bakeCitationsForExport(
  text: string,
  details: Record<string, ChatCitation>,
  heading: string,
): string {
  if (!text) return text;
  const normalized = normalizeCitationMarkers(text);
  const labelByGroup: Record<string, number> = {};
  const entries: BakedCitationEntry[] = [];

  const bakeSpan = (_match: string, body: string) => {
    const labels: number[] = [];
    for (const rawRef of body.split(CITATION_SEPARATOR)) {
      const data = buildCitationDisplayData(rawRef.trim());
      if (!data) continue;
      const detail = details[data.citationId];
      if (!detail) continue;
      const groupId = `${data.type}_${data.groupKey}_${data.itemId}`;
      if (!labelByGroup[groupId]) {
        labelByGroup[groupId] = entries.length + 1;
        entries.push({ label: entries.length + 1, detail, itemId: data.itemId });
      }
      const label = labelByGroup[groupId];
      if (!labels.includes(label)) labels.push(label);
    }
    return labels.map((label) => `[${label}]`).join('');
  };

  const bakeSegment = (segment: string) =>
    segment.replace(CITATION_SPAN_RE, bakeSpan).replace(CITATION_STRAY_MARKER_RE, '');

  const out: string[] = [];
  let last = 0;
  for (const match of normalized.matchAll(CITATION_CODE_RE)) {
    const start = match.index ?? 0;
    if (start > last) out.push(bakeSegment(normalized.slice(last, start)));
    out.push(match[0]);
    last = start + match[0].length;
  }
  if (last < normalized.length) out.push(bakeSegment(normalized.slice(last)));

  const body = stripCitationHandles(out.join(''));
  if (!entries.length) return body;

  const lines = entries.map((entry) => `${entry.label}. ${formatCitationExportLine(entry)}`);
  return `${body.replace(/\s+$/, '')}\n\n## ${heading}\n\n${lines.join('\n')}\n`;
}


return {stripCitationMarkers,stripCitationHandles,bakeCitationsForExport};
}
