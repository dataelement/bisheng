import { useEffect, useRef, type RefObject } from 'react';

function isVisible(element: HTMLElement) {
  return element.isConnected && !element.closest('[hidden]');
}

function focusFallbacks(target: Element, viewport: HTMLElement) {
  const candidates: HTMLElement[] = [];
  for (let node = target.closest('[data-tree-node]'); node; node = node.parentElement?.closest('[data-tree-node]') ?? null) {
    const row = node.querySelector(':scope > [data-tree-row]');
    candidates.push(...(row?.querySelectorAll<HTMLElement>('[data-tree-disclosure], [data-tree-target]:not(:disabled)') ?? []));
  }
  const group = target.closest('[data-tree-group]')?.querySelector<HTMLElement>('[data-tree-group-toggle]');
  if (group) candidates.push(group);
  return [...candidates, viewport];
}

function revealRow(viewport: HTMLElement, target: HTMLElement) {
  const row = target.closest('[data-tree-row]');
  const rect = row?.getBoundingClientRect();
  if (!rect) return;

  const bounds = viewport.getBoundingClientRect();
  const header = row?.closest('[data-tree-group]')?.querySelector('[data-tree-group-header]');
  const top = bounds.top + viewport.clientTop + (header?.getBoundingClientRect().height ?? 0);
  const bottom = bounds.top + viewport.clientTop + viewport.clientHeight;
  if (rect.top < top) viewport.scrollTop += rect.top - top;
  else if (rect.bottom > bottom) viewport.scrollTop += rect.bottom - bottom;

  const left = bounds.left + viewport.clientLeft;
  const right = left + viewport.clientWidth;
  const label = target.querySelector<HTMLElement>('[data-tree-name]');
  if (!label) return;
  const labelLeft = label.getBoundingClientRect().left;
  // Measure the rendered name after reserving the current row's action gutter.
  label.style.setProperty('--tree-name-room', `${right - labelLeft}px`);
  const nameRect = label.firstElementChild?.getBoundingClientRect();
  if (nameRect && (nameRect.width === 0 || nameRect.right <= left)) {
    viewport.scrollLeft += labelLeft - left - 24;
  }
}

export function useTreeViewport(
  viewportRef: RefObject<HTMLElement>,
  contentRef: RefObject<HTMLElement>,
  revealKey?: string | number,
) {
  const previous = useRef<{ current: HTMLElement | null; key: typeof revealKey }>();

  useEffect(() => {
    const viewport = viewportRef.current;
    const content = contentRef.current;
    if (!viewport || !content) return;

    let frame = 0;
    let measuredScrollLeft = viewport.scrollLeft;
    let focused: HTMLElement | undefined;
    let fallbacks: HTMLElement[] = [];

    const measure = () => {
      frame = 0;
      if (!viewport.clientWidth) return;

      if (focused && !isVisible(focused) && (document.activeElement === document.body || document.activeElement === focused)) {
        const fallback = fallbacks.find((element) => element !== focused && isVisible(element));
        focused = undefined;
        fallback?.focus();
      }

      const current = content.querySelector<HTMLElement>('[data-tree-target][aria-current]');
      if (current && (previous.current?.current !== current || previous.current?.key !== revealKey)) revealRow(viewport, current);
      previous.current = { current, key: revealKey };

      measuredScrollLeft = viewport.scrollLeft;
      const right = viewport.getBoundingClientRect().left + viewport.clientLeft + viewport.clientWidth;
      // Batch geometry reads before updating the visible labels.
      const labels = Array.from(content.querySelectorAll<HTMLElement>('[data-tree-name]'), (label) => ({
        label, room: right - label.getBoundingClientRect().left,
      }));
      for (const { label, room } of labels) label.style.setProperty('--tree-name-room', `${room}px`);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    const handleScroll = () => { if (viewport.scrollLeft !== measuredScrollLeft) schedule(); };
    const handleWheel = (event: WheelEvent) => {
      if (!event.shiftKey || event.ctrlKey || event.deltaX || !event.deltaY ||
        event.defaultPrevented || !event.cancelable || viewport.scrollWidth <= viewport.clientWidth) return;
      event.preventDefault();
      const scale = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16
        : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? viewport.clientWidth : 1;
      viewport.scrollLeft += event.deltaY * scale;
    };
    const handleFocusIn = (event: FocusEvent) => {
      if (!(event.target instanceof HTMLElement)) return;
      focused = event.target;
      fallbacks = focusFallbacks(focused, viewport);
    };
    const handleFocusOut = (event: FocusEvent) => {
      if (event.relatedTarget instanceof Node && !viewport.contains(event.relatedTarget)) {
        focused = undefined;
        fallbacks = [];
      }
    };

    const resize = new ResizeObserver(schedule);
    resize.observe(viewport);
    resize.observe(content);
    const mutation = new MutationObserver(schedule);
    mutation.observe(content, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['aria-current', 'hidden'] });
    viewport.addEventListener('scroll', handleScroll, { passive: true });
    viewport.addEventListener('wheel', handleWheel, { passive: false });
    viewport.addEventListener('focusin', handleFocusIn);
    viewport.addEventListener('focusout', handleFocusOut);
    schedule();

    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutation.disconnect();
      viewport.removeEventListener('scroll', handleScroll);
      viewport.removeEventListener('wheel', handleWheel);
      viewport.removeEventListener('focusin', handleFocusIn);
      viewport.removeEventListener('focusout', handleFocusOut);
    };
  }, [viewportRef, contentRef, revealKey]);
}
