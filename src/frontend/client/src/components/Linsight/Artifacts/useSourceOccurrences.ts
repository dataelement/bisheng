/**
 * F074: ties the report's citation badges to the source pane.
 *
 *  - marks the badges citing the passage being checked (`data-compare-active`)
 *    so they stay visible while the reader's eyes are on the source;
 *  - counts the distinct passages of the SAME file (same knowledge document,
 *    even across citation groups) that the report cites, and steps through
 *    them — each step moves the source to the next passage and scrolls the
 *    report to the nearest badge citing it (sourcePassages).
 *
 * Works on the rendered report DOM: the badges already carry
 * data-citation-id / data-citation-item-id (Markdown.tsx), and the order a
 * reader meets them in is exactly the DOM order. Badges are tracked by that
 * position, not by node: Markdown rebuilds its custom nodes on every render
 * (inline `components`), so a remembered node goes stale after one re-render.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatCitation } from '~/api/chatApi';
import type { CitationDocumentPreviewState } from '~/components/Chat/Messages/Content/CitationDocumentPreviewDrawer';
import type { SourcePreview } from './useWorkspacePanel';
import type { SourceOccurrence } from './SourcePane';
import { type BadgeRef, fileKeyOf, listSourcePassages, nearestBadge, passageKeyOf } from './sourcePassages';

const BADGE_SELECTOR = '[data-citation-trigger="true"][data-citation-id]';
const ACTIVE_ATTR = 'data-compare-active';

interface Options {
    citations?: ChatCitation[] | null;
    sourcePreview: SourcePreview | null;
    onOpenSource?: (preview: SourcePreview) => void;
}

const refOf = (el: HTMLElement): BadgeRef => ({
    citationId: el.dataset.citationId,
    itemId: el.dataset.citationItemId,
});

export function useSourceOccurrences({ citations, sourcePreview, onOpenSource }: Options) {
    const reportRef = useRef<HTMLDivElement>(null);
    // Positions among all report badges (DOM order), stable across re-renders.
    const clickedIndexRef = useRef<number | null>(null);
    const activeIndexRef = useRef<number | null>(null);
    const [occurrence, setOccurrence] = useState<SourceOccurrence | null>(null);

    const allBadges = useCallback(
        () => Array.from(reportRef.current?.querySelectorAll<HTMLElement>(BADGE_SELECTOR) ?? []),
        [],
    );

    /** The passages of the file `citationId` belongs to, in stepping order. */
    const passagesOf = useCallback(
        (citationId?: string) =>
            listSourcePassages(citations, allBadges().map(refOf), fileKeyOf(citations, citationId)),
        [allBadges, citations],
    );

    // Every badge citing the active passage is marked, not only the one clicked.
    const applyMark = useCallback(() => {
        const badges = allBadges();
        const activeIndex = activeIndexRef.current;
        const activeKey = activeIndex != null && badges[activeIndex] ? passageKeyOf(citations, refOf(badges[activeIndex])) : null;
        badges.forEach((el) => {
            const active = activeKey != null && passageKeyOf(citations, refOf(el)) === activeKey;
            if (active !== el.hasAttribute(ACTIVE_ATTR)) {
                if (active) el.setAttribute(ACTIVE_ATTR, 'true');
                else el.removeAttribute(ACTIVE_ATTR);
            }
        });
    }, [allBadges, citations]);

    /** Remember which badge was clicked — the same chunk can be cited twice. */
    const handleReportClickCapture = useCallback(
        (e: React.MouseEvent) => {
            const badge = (e.target as Element | null)?.closest?.(BADGE_SELECTOR) as HTMLElement | null;
            if (!badge) return;
            const index = allBadges().indexOf(badge);
            if (index >= 0) clickedIndexRef.current = index;
        },
        [allBadges],
    );

    /** Markdown's citation click → the source, tagged with the badge clicked
     *  (the capture handler above has run by then). */
    const openFromReport = useCallback(
        (preview: CitationDocumentPreviewState) => {
            const badgeIndex = clickedIndexRef.current ?? undefined;
            clickedIndexRef.current = null;
            onOpenSource?.({ ...preview, badgeIndex });
        },
        [onOpenSource],
    );

    useEffect(() => {
        activeIndexRef.current = null;

        if (!sourcePreview) {
            applyMark();
            setOccurrence(null);
            return undefined;
        }

        const { detail, itemId } = sourcePreview;
        const resolve = () => {
            const badges = allBadges();
            const passages = passagesOf(detail.citationId);
            const list = passages.flatMap((p) => p.badges);
            const matchesItem = (i: number) => !itemId || badges[i]?.dataset.citationItemId === itemId;
            const tagged = sourcePreview.badgeIndex;
            const active =
                (tagged != null && list.includes(tagged) && matchesItem(tagged) ? tagged : null) ??
                list.find((i) => badges[i].dataset.citationId === detail.citationId && matchesItem(i)) ??
                list.find(matchesItem) ??
                null;
            activeIndexRef.current = active;
            applyMark();
            // A panel mounted mid-compare (fullscreen, crossing 1024px) starts at
            // the top; bring the badge being checked back into view. 'nearest'
            // leaves an already-visible badge (the one just clicked) alone.
            if (active != null) badges[active]?.scrollIntoView({ block: 'nearest' });
            const position = active == null ? -1 : passages.findIndex((p) => p.badges.includes(active));
            setOccurrence(position < 0 ? null : { index: position + 1, total: passages.length });
        };
        resolve();

        // Markdown rebuilds its nodes on re-render, and a freshly mounted panel
        // (fullscreen / narrow layout) may render the report after this runs:
        // re-mark on every rebuild, and resolve again if nothing matched yet.
        const root = reportRef.current;
        if (!root) return undefined;
        const observer = new MutationObserver(() => (activeIndexRef.current == null ? resolve() : applyMark()));
        observer.observe(root, { childList: true, subtree: true });
        return () => observer.disconnect();
    }, [allBadges, applyMark, passagesOf, sourcePreview]);

    const revealActive = useCallback(() => {
        // After a tab switch the report is display:none until the next paint.
        requestAnimationFrame(() => {
            const index = activeIndexRef.current;
            if (index != null) allBadges()[index]?.scrollIntoView({ block: 'center' });
        });
    }, [allBadges]);

    const step = useCallback(
        (delta: 1 | -1) => {
            const current = activeIndexRef.current;
            if (!sourcePreview || current == null || !onOpenSource) return;
            const passages = passagesOf(sourcePreview.detail.citationId);
            const position = passages.findIndex((p) => p.badges.includes(current));
            if (position < 0 || passages.length < 2) return;
            const target = passages[(position + delta + passages.length) % passages.length];
            const nextIndex = nearestBadge(target, current);
            const next = allBadges()[nextIndex];
            next.scrollIntoView({ block: 'center', behavior: 'smooth' });
            const nextCitationId = next.dataset.citationId;
            // Same group → keep the resolved detail we already have.
            const detail =
                nextCitationId === sourcePreview.detail.citationId
                    ? sourcePreview.detail
                    : citations?.find((c) => c.citationId === nextCitationId) ?? sourcePreview.detail;
            onOpenSource({ detail, itemId: next.dataset.citationItemId, locateChunk: true, badgeIndex: nextIndex });
        },
        [allBadges, citations, onOpenSource, passagesOf, sourcePreview],
    );

    return { reportRef, handleReportClickCapture, openFromReport, occurrence, step, revealActive };
}
