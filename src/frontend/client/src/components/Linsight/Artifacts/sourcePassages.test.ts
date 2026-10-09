import type { ChatCitation } from '~/api/chatApi';
import { fileKeyOf, listSourcePassages, nearestBadge, passageKeyOf } from './sourcePassages';

const rag = (citationId: string, documentId: number, items: { itemId: string; chunkId?: string; chunkIndex?: number; content?: string }[]): ChatCitation => ({
    citationId,
    type: 'rag',
    sourcePayload: { documentId, items },
});

// Two handles (S1, S2) carry the same chunk 3 of document 7; S3 is chunk 1; S4 is another file.
const citations = [
    rag('S1', 7, [{ itemId: '3', chunkIndex: 3, content: 'c3' }]),
    rag('S2', 7, [{ itemId: '3', chunkIndex: 3, content: 'c3' }, { itemId: '5', chunkIndex: 5, content: 'c5' }]),
    rag('S3', 7, [{ itemId: '1', chunkIndex: 1, content: 'c1' }]),
    rag('S4', 9, [{ itemId: '3', chunkIndex: 3, content: 'x3' }]),
];

describe('passageKeyOf', () => {
    it('treats the same chunk under different handles as one passage', () => {
        expect(passageKeyOf(citations, { citationId: 'S1', itemId: '3' })).toBe(passageKeyOf(citations, { citationId: 'S2', itemId: '3' }));
    });

    it('keeps the same chunk index of different files apart', () => {
        expect(passageKeyOf(citations, { citationId: 'S1', itemId: '3' })).not.toBe(passageKeyOf(citations, { citationId: 'S4', itemId: '3' }));
    });

    it('prefers the chunk id when the item has one', () => {
        const withIds = [rag('A', 1, [{ itemId: '0', chunkId: 'k1', chunkIndex: 0 }]), rag('B', 1, [{ itemId: 'k1', chunkId: 'k1' }])];
        expect(passageKeyOf(withIds, { citationId: 'A', itemId: '0' })).toBe(passageKeyOf(withIds, { citationId: 'B', itemId: 'k1' }));
    });
});

describe('listSourcePassages', () => {
    const badges = [
        { citationId: 'S1', itemId: '3' }, // 0
        { citationId: 'S4', itemId: '3' }, // 1 other file
        { citationId: 'S2', itemId: '5' }, // 2
        { citationId: 'S2', itemId: '3' }, // 3 same passage as 0
        { citationId: 'S3', itemId: '1' }, // 4
    ];

    it('dedupes badges into passages ordered by position in the file', () => {
        const passages = listSourcePassages(citations, badges, fileKeyOf(citations, 'S1'));
        expect(passages.map((p) => p.chunkIndex)).toEqual([1, 3, 5]);
        expect(passages.map((p) => p.badges)).toEqual([[4], [0, 3], [2]]);
    });

    it('falls back to report order when a passage has no position', () => {
        const mixed = [...citations, rag('S5', 7, [{ itemId: 'u', content: 'no index' }])];
        const passages = listSourcePassages(mixed, [...badges, { citationId: 'S5', itemId: 'u' }], 'doc:7');
        expect(passages.map((p) => p.badges[0])).toEqual([0, 2, 4, 5]);
    });
});

describe('nearestBadge', () => {
    it('picks the badge of the passage closest to the current one', () => {
        expect(nearestBadge({ key: 'k', badges: [2, 10, 30], chunkIndex: 0 }, 12)).toBe(10);
    });
});
