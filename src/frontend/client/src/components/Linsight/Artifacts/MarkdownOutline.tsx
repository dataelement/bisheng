/**
 * MarkdownOutline — the "chapter spine" for a markdown deliverable preview.
 *
 * Collapsed, it is a column of ticks hugging the right edge: one per heading,
 * length shrinking with depth and right-aligned, so the staircase on its left
 * edge reads as the document's own silhouette. The tick for the section you're
 * reading takes the brand colour, which makes the rail a position indicator as
 * much as a control — something a toolbar button can't be.
 *
 * Bringing the pointer near the right edge (or focusing / tapping the rail)
 * cross-fades it into a floating outline. The document never reflows: the
 * preview panel is as narrow as 440px and a docked sidebar would leave Chinese
 * body text ~260px to work with.
 *
 * Mounted by PreviewBody's markdown branch, which covers all four preview
 * surfaces (chat inline, desktop fullscreen, mobile drawer, /linsight sheet).
 */
import {
    useCallback,
    useEffect,
    useId,
    useMemo,
    useRef,
    useState,
    type KeyboardEvent as ReactKeyboardEvent,
    type MutableRefObject,
    type RefObject,
} from 'react';
import { useLocalize, useScrollRevealRef } from '~/hooks';
import { cn } from '~/utils';
import { useScrollFade } from '../Execution/useScrollFade';
import { TICK_LENGTHS, getScrollParent } from './markdownOutlineUtils';
import { useMarkdownOutline } from './useMarkdownOutline';

/** How close to the right edge the pointer must come to reveal the outline. */
const EDGE_ZONE = 56;
/** Opening is immediate — the right edge of the panel is a terminus rather than
 *  a corridor, so there is no sweep-through to debounce away, and any delay here
 *  stacks on top of the fade and reads as lag. Closing stays lazy so the pointer
 *  has time to travel from the rail onto the card. */
const CLOSE_DELAY = 200;
/** Below this an outline isn't navigation, it's noise. */
const MIN_HEADINGS = 2;

const tickLength = (depth: number) => TICK_LENGTHS[Math.min(depth, TICK_LENGTHS.length) - 1];
const itemIndent = (depth: number) => Math.min(depth - 1, 3) * 12;

interface MarkdownOutlineProps {
    /** The rendered `.bs-mkdown` container to read headings from. */
    contentRef: RefObject<HTMLElement>;
    /** Changes when the document changes, triggering a re-scan. */
    contentKey: string;
}

export function MarkdownOutline({ contentRef, contentKey }: MarkdownOutlineProps) {
    const localize = useLocalize();
    // Fullscreen mounts a second preview alongside the docked one — the panel
    // and its aria-controls target must not collide on a shared DOM id.
    const listId = `markdown-outline-${useId()}`;
    const {
        headings,
        activeIndex,
        railHeadings,
        railActiveIndex,
        gap,
        railTop,
        maxCardHeight,
        scrollTo,
    } = useMarkdownOutline(contentRef, contentKey);

    const [open, setOpen] = useState(false);
    const openRef = useRef(open);
    openRef.current = open;
    const cardRef = useRef<HTMLElement | null>(null);
    const railRef = useRef<HTMLButtonElement | null>(null);
    const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

    // The list needs two refs: one to measure the soft top/bottom fade, one to
    // reveal the scrollbar only while scrolling (it would otherwise sit there
    // competing with the outline itself).
    const { ref: listRef, onScroll: onListScroll, maskStyle } = useScrollFade<HTMLDivElement>(headings);
    const revealListRef = useScrollRevealRef<HTMLDivElement>();
    const setListRef = useCallback(
        (node: HTMLDivElement | null) => {
            (listRef as MutableRefObject<HTMLDivElement | null>).current = node;
            revealListRef(node);
        },
        [listRef, revealListRef],
    );

    const openNow = useCallback(() => {
        clearTimeout(timerRef.current);
        setOpen(true);
    }, []);

    const closeSoon = useCallback(() => {
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => setOpen(false), CLOSE_DELAY);
    }, []);

    /** Cancel a pending close without opening — used while the pointer is on the card. */
    const holdOpen = useCallback(() => {
        clearTimeout(timerRef.current);
    }, []);

    useEffect(() => () => clearTimeout(timerRef.current), []);

    const coarsePointer = useMemo(
        () => window.matchMedia?.('(pointer: coarse)').matches ?? false,
        [],
    );

    // Proximity reveal (pointer devices). Listening on the scroller instead of
    // stretching a hit area across the right gutter keeps text selection intact
    // everywhere except the ~16px the ticks themselves occupy.
    useEffect(() => {
        if (coarsePointer || headings.length < MIN_HEADINGS) {
            return undefined;
        }
        const scroller = getScrollParent(contentRef.current);
        if (!scroller) {
            return undefined;
        }
        const onMove = (event: PointerEvent) => {
            if (scroller.getBoundingClientRect().right - event.clientX <= EDGE_ZONE) {
                openNow();
            } else if (cardRef.current?.contains(event.target as Node)) {
                // On the card but left of the edge zone: stay open for as long as
                // the pointer rests there, however far it is from the rail.
                holdOpen();
            } else if (openRef.current) {
                closeSoon();
            }
        };
        const onLeave = () => closeSoon();
        scroller.addEventListener('pointermove', onMove, { passive: true });
        scroller.addEventListener('pointerleave', onLeave);
        return () => {
            scroller.removeEventListener('pointermove', onMove);
            scroller.removeEventListener('pointerleave', onLeave);
        };
    }, [closeSoon, coarsePointer, contentRef, headings.length, holdOpen, openNow]);

    // Tap-outside and Esc both dismiss; Esc hands focus back to the rail.
    useEffect(() => {
        if (!open) {
            return undefined;
        }
        const onPointerDown = (event: PointerEvent) => {
            const target = event.target as Node;
            if (!cardRef.current?.contains(target) && !railRef.current?.contains(target)) {
                setOpen(false);
            }
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
                railRef.current?.focus();
            }
        };
        document.addEventListener('pointerdown', onPointerDown);
        document.addEventListener('keydown', onKeyDown);
        return () => {
            document.removeEventListener('pointerdown', onPointerDown);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [open]);

    const handleJump = useCallback(
        (index: number) => {
            scrollTo(index);
            if (coarsePointer) {
                setOpen(false);
            }
        },
        [coarsePointer, scrollTo],
    );

    // Roving focus through the outline; Home/End jump to the document's ends.
    const handleListKeyDown = useCallback((event: ReactKeyboardEvent<HTMLElement>) => {
        const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End'];
        if (!keys.includes(event.key)) {
            return;
        }
        event.preventDefault();
        const items = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>('button[data-outline-item]'),
        );
        const current = items.indexOf(document.activeElement as HTMLButtonElement);
        const next =
            event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? items.length - 1
                  : Math.min(items.length - 1, Math.max(0, current + (event.key === 'ArrowDown' ? 1 : -1)));
        items[next]?.focus();
    }, []);

    if (headings.length < MIN_HEADINGS) {
        return null;
    }

    return (
        // Sticky + zero height pins the spine to the scrollport while the rest of
        // the preview scrolls underneath it.
        <div className="pointer-events-none sticky top-0 z-20 h-0">
            <div className="absolute right-2 -translate-y-1/2" style={{ top: railTop }}>
                <button
                    ref={railRef}
                    type="button"
                    aria-label={localize('workstation.toc.open')}
                    aria-expanded={open}
                    aria-controls={listId}
                    onClick={() => setOpen((prev) => !prev)}
                    // Keyboard focus opens the outline; a tap must not, or the
                    // click that follows would toggle it straight back shut.
                    onFocus={(event) => {
                        if (event.currentTarget.matches(':focus-visible')) {
                            setOpen(true);
                        }
                    }}
                    className={cn(
                        'pointer-events-auto flex flex-col items-end py-2 pl-2 outline-none transition-opacity duration-100',
                        // Two-stage reveal: the ticks wake when the pointer is
                        // anywhere over the document, then hand off to the card.
                        'opacity-60 group-hover/mk:opacity-100 focus-visible:opacity-100',
                        open && 'pointer-events-none opacity-0',
                    )}
                    style={{ gap: `${gap}px` }}
                >
                    {railHeadings.map((heading, i) => (
                        <span
                            key={heading.id}
                            className={cn(
                                'h-0.5 rounded-full transition-colors duration-200',
                                i === railActiveIndex ? 'bg-blue-500' : 'bg-border-deep',
                            )}
                            style={{ width: `${tickLength(heading.depth)}px` }}
                        />
                    ))}
                </button>

                <nav
                    ref={cardRef}
                    id={listId}
                    aria-label={localize('workstation.toc.label')}
                    aria-hidden={!open}
                    onKeyDown={handleListKeyDown}
                    className={cn(
                        'absolute right-0 top-1/2 w-[240px] -translate-y-1/2 overflow-hidden rounded-[10px]',
                        'border border-[#ebecf0] bg-white shadow-[0px_4px_16px_rgba(0,0,0,0.08)]',
                        'transition-[opacity,transform] ease-out motion-reduce:transition-none',
                        'coarse-pointer:w-[min(260px,68vw)]',
                        // Opens fast enough to feel like a direct response to the
                        // pointer; closes a touch slower so it doesn't snap away.
                        open
                            ? 'pointer-events-auto translate-x-0 opacity-100 duration-100'
                            : 'pointer-events-none translate-x-1 opacity-0 duration-150',
                    )}
                >
                    <div
                        ref={setListRef}
                        onScroll={onListScroll}
                        style={{ ...maskStyle, maxHeight: maxCardHeight }}
                        className="scrollbar-on-scroll overflow-y-auto p-1.5"
                    >
                        {headings.map((heading) => {
                            const current = heading.index === activeIndex;
                            return (
                                <button
                                    key={heading.id}
                                    type="button"
                                    data-outline-item
                                    tabIndex={open ? 0 : -1}
                                    onClick={() => handleJump(heading.index)}
                                    style={{ paddingLeft: `${8 + itemIndent(heading.depth)}px` }}
                                    className={cn(
                                        'block w-full truncate rounded-md py-1 pr-2 text-left text-[13px] leading-[1.55] transition-colors',
                                        // Depth reads as recession, so the type
                                        // scale stays out of it.
                                        heading.depth === 1 && 'text-text-1',
                                        heading.depth === 2 && 'text-text-2',
                                        heading.depth >= 3 && 'text-text-3',
                                        current
                                            ? 'bg-blue-500/[0.07] font-medium text-blue-600'
                                            : 'hover:bg-fill-1',
                                    )}
                                    title={heading.text}
                                >
                                    {heading.text}
                                </button>
                            );
                        })}
                    </div>
                </nav>
            </div>
        </div>
    );
}
