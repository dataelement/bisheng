export function extractMarkdownSection(markdown: string, heading: string): string {
    const pattern = new RegExp(`^##\\s+${heading}\\s*$`, "m");
    const match = markdown.match(pattern);
    if (!match || match.index === undefined) return "";
    const start = match.index + match[0].length;
    const rest = markdown.slice(start);
    const nextHeading = rest.search(/^##\s+/m);
    return (nextHeading >= 0 ? rest.slice(0, nextHeading) : rest).trim();
}

interface TranscriptCue {
    /** Raw timestamp label, e.g. "00:00:03 - 00:00:05". */
    time: string;
    text: string;
}

/** A cue line opens with its timestamp in brackets: "[00:00:03 - 00:00:05] …". */
const CUE_PATTERN = /^\[(\d{1,2}:\d{2}(?::\d{2})?(?:\s*-\s*\d{1,2}:\d{2}(?::\d{2})?)?)\]\s*/;

/**
 * Split a transcript into timestamp/text pairs so the time can be rendered as its
 * own label instead of running inline with the sentence. Lines without a leading
 * timestamp continue the cue above them; text before the first cue is returned as
 * `preamble`. No cue found → the caller falls back to plain markdown.
 */
export function parseTranscriptCues(markdown: string): { preamble: string; cues: TranscriptCue[] } {
    const cues: TranscriptCue[] = [];
    const preambleLines: string[] = [];

    for (const rawLine of markdown.split("\n")) {
        const line = rawLine.trim();
        if (!line) continue;
        const match = line.match(CUE_PATTERN);
        if (match) {
            cues.push({ time: match[1].replace(/\s*-\s*/, " - "), text: line.slice(match[0].length).trim() });
        } else if (cues.length) {
            const last = cues[cues.length - 1];
            last.text = last.text ? `${last.text} ${line}` : line;
        } else {
            preambleLines.push(line);
        }
    }

    return { preamble: preambleLines.join("\n\n"), cues };
}
