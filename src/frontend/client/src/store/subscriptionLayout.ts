import { atom } from 'recoil';

/**
 * Width (px) of the channel article-detail area (detail panel + splitter) on PC.
 *
 * Written by ChannelLayout: the actual right-area width when an article is open,
 * 0 when closed / on H5 / after leaving the channel view (e.g. to the square).
 *
 * The persistent 频道/广场 tab — rendered once above both the channel and square
 * views — reads this to offset itself leftward, so it stays pinned to the right
 * edge of the article-list column (and slides left when the detail panel opens)
 * instead of hugging the whole content area's right edge.
 *
 * Pure client UI state — never sent to the backend, issues no HTTP (constitution C7).
 */
export const subscriptionDetailPaneWidthState = atom<number>({
    key: 'subscriptionDetailPaneWidth',
    default: 0,
});
