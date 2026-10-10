/**
 * F071: group the report's citation badges by the source passage they cite.
 *
 * The source pane's previous / next steps through passages of one file, not
 * through badges: a report often cites the same chunk many times (31 badges,
 * 6 passages), and stepping badge by badge would leave the source pane still
 * on most steps. Different citation handles can carry the same chunk, so the
 * passage is identified by the chunk itself (id, then index, then text), never
 * by the handle.
 */
import type { ChatCitation } from '~/api/chatApi';
import { getCitationItem } from '~/components/Chat/Messages/Content/citationUtils';

export interface BadgeRef {
    citationId?: string;
    itemId?: string;
}

export interface SourcePassage {
    key: string;
    /** Positions of the badges citing this passage, in report (DOM) order. */
    badges: number[];
    /** Where the passage sits in the file, when known — used for ordering. */
    chunkIndex: number | null;
}

/** Key of the file a badge cites: the knowledge document when named. */
export function fileKeyOf(citations: ChatCitation[] | null | undefined, citationId?: string): string {
    const citation = citations?.find((c) => c.citationId === citationId);
    const documentId = citation?.sourcePayload?.documentId;
    return documentId != null ? `doc:${documentId}` : `cid:${citationId ?? ''}`;
}

function passageOf(citations: ChatCitation[] | null | undefined, badge: BadgeRef) {
    const citation = citations?.find((c) => c.citationId === badge.citationId) ?? null;
    const item = badge.itemId ? getCitationItem(citation, badge.itemId) : null;
    const chunkIndex = item?.chunkIndex != null && Number.isFinite(Number(item.chunkIndex)) ? Number(item.chunkIndex) : null;
    const chunk =
        (item?.chunkId && `id:${item.chunkId}`) ||
        (chunkIndex != null && `idx:${chunkIndex}`) ||
        (item?.content && `text:${item.content.slice(0, 80)}`) ||
        `ref:${badge.citationId ?? ''}#${badge.itemId ?? ''}`;
    return { key: `${fileKeyOf(citations, badge.citationId)}|${chunk}`, chunkIndex };
}

/** Key of the passage a badge cites. */
export function passageKeyOf(citations: ChatCitation[] | null | undefined, badge: BadgeRef): string {
    return passageOf(citations, badge).key;
}

/**
 * The passages of `fileKey` cited in the report. Ordered by position in the
 * file when every passage knows it — "next" then moves the source pane
 * downward — otherwise by first appearance in the report.
 */
export function listSourcePassages(
    citations: ChatCitation[] | null | undefined,
    badges: BadgeRef[],
    fileKey: string,
): SourcePassage[] {
    const byKey = new Map<string, SourcePassage>();
    badges.forEach((badge, i) => {
        if (fileKeyOf(citations, badge.citationId) !== fileKey) return;
        const { key, chunkIndex } = passageOf(citations, badge);
        const passage = byKey.get(key);
        if (passage) passage.badges.push(i);
        else byKey.set(key, { key, badges: [i], chunkIndex });
    });
    const passages = [...byKey.values()];
    if (passages.every((p) => p.chunkIndex != null)) {
        // Stable: equal indices keep report order.
        passages.sort((a, b) => (a.chunkIndex as number) - (b.chunkIndex as number));
    }
    return passages;
}

/** The badge of `passage` closest to `from` in the report, so stepping scrolls the report least. */
export function nearestBadge(passage: SourcePassage, from: number): number {
    return passage.badges.reduce((best, i) => (Math.abs(i - from) < Math.abs(best - from) ? i : best));
}
