import { asRecord } from './normalizeHistory';
export interface LegacyWebReference { title?: string; url?: string; snippet?: string; content?: string; source?: string; datePublished?: string; date?: string; [key: string]: string | undefined }
export interface MessageContent {
  text: string;
  reasoning: string;
  referenceText: string;
  webContent: LegacyWebReference[];
}
/** Client-compatible inline reasoning and legacy web-reference envelopes. */
export function splitMessageContent(value: string): MessageContent {
  const think = /<think>(.*?)<\/think>/s.exec(value);
  const text = think ? value.replace(think[0], '') : value;
  const web = /:::web([\s\S]*?):::/.exec(text);
  let webContent: LegacyWebReference[] = [];
  if (web) {
    try { const parsed: unknown = JSON.parse(web[1].trim()); if (Array.isArray(parsed)) webContent = parsed.map(value => Object.fromEntries(Object.entries(asRecord(value)).filter((entry): entry is [string, string] => typeof entry[1] === 'string'))); } catch { /* Keep malformed content visible in the message. */ }
  }
  return { text, reasoning: think?.[1] ?? '', referenceText: web ? text.replace(web[0], '').trim() : text.trim(), webContent };
}
