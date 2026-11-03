import { normalizeCitationMarkers } from './markers';

const prefixes = ['knowledgesearch_', 'websearch_', 'tempsearch_', 'articlesearch_'];
const bareReference = new RegExp(`(?<![\\w/:])(?:${prefixes.join('|')})[a-fA-F0-9]+:\\d+(?![\\w:.-])`, 'g');

function hideProse(content: string, isTail: boolean): string {
  let text = normalizeCitationMarkers(content)
    .replace(/\ue200[^\ue202]*\ue202/g, '')
    // An incomplete protocol span must not swallow the following prose line.
    .replace(/\ue200[A-Za-z0-9_:.\-\ue201]*/g, '')
    .replace(bareReference, '')
    .replace(/[\ue201\ue202]/g, '');
  if (!isTail) return text;

  const escapedMarker = /\\+(?:u(?:[eE](?:2(?:0[012]?)?)?)?)?$/.exec(text);
  if (escapedMarker) {
    const slashCount = /^\\+/.exec(escapedMarker[0])?.[0].length ?? 0;
    if (slashCount % 2) text = text.slice(0, escapedMarker.index) + '\\'.repeat(slashCount - 1);
  }
  const partial = /(?<![\w/:])([A-Za-z_][A-Za-z0-9_:]*)$/.exec(text);
  if (partial && prefixes.some(prefix => prefix.startsWith(partial[0]) || (
    partial[0].startsWith(prefix) && /^[a-fA-F0-9]*(?::\d*)?$/.test(partial[0].slice(prefix.length))
  ))) {
    text = text.slice(0, partial.index);
  }
  return text;
}

/** Display-only filtering: the caller retains the raw response for final validation and cancellation. */
export function hideStreamingCitations(content: string): string {
  // Include unfinished code fences and link destinations, which remain literal while streaming.
  const protectedMarkdown = /(`+)[\s\S]*?(?:\1(?!`)|(?![\s\S]))|^ {0,3}(~{3,})[\s\S]*?(?:\2(?!~)|(?![\s\S]))|!?\[[^\]\n]*\]\([^\n)]*(?:\)|(?=\n)|(?![\s\S]))|https?:\/\/[^\s<>]+|^(?: {4}|\t)[^\n]*(?:\n|$)/gm;
  let display = '';
  let cursor = 0;
  for (const match of content.matchAll(protectedMarkdown)) {
    display += hideProse(content.slice(cursor, match.index), false) + match[0];
    cursor = match.index + match[0].length;
  }
  return display + hideProse(content.slice(cursor), true);
}
