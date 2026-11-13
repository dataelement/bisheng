import { useEffect, type RefObject } from "react";

export function useKnowledgeTreeScroll(viewportRef: RefObject<HTMLElement>) {
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    let frame = 0;
    let measuredScrollLeft = viewport.scrollLeft;
    const measure = () => {
      frame = 0;
      measuredScrollLeft = viewport.scrollLeft;
      const right = viewport.getBoundingClientRect().left + viewport.clientLeft + viewport.clientWidth;
      // Read all positions before updating the labels, once per frame.
      const labels = Array.from(viewport.querySelectorAll<HTMLElement>("[data-tree-name]"), (label) => ({
        label, room: right - label.getBoundingClientRect().left,
      }));
      for (const { label, room } of labels) label.style.setProperty("--tree-name-room", `${room}px`);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    const handleScroll = () => { if (viewport.scrollLeft !== measuredScrollLeft) schedule(); };
    const handleWheel = (event: WheelEvent) => {
      // Keep native horizontal gestures and support mouse wheels that report Shift+wheel vertically.
      if (!event.shiftKey || event.ctrlKey || event.deltaX || !event.deltaY ||
        event.defaultPrevented || !event.cancelable || viewport.scrollWidth <= viewport.clientWidth) return;
      event.preventDefault();
      const scale = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16
        : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? viewport.clientWidth : 1;
      viewport.scrollLeft += event.deltaY * scale;
    };

    const resize = new ResizeObserver(schedule);
    resize.observe(viewport);
    if (viewport.firstElementChild) resize.observe(viewport.firstElementChild);
    const mutation = new MutationObserver(schedule);
    mutation.observe(viewport, { childList: true, subtree: true, characterData: true });
    viewport.addEventListener("scroll", handleScroll, { passive: true });
    viewport.addEventListener("wheel", handleWheel, { passive: false });
    schedule();

    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutation.disconnect();
      viewport.removeEventListener("scroll", handleScroll);
      viewport.removeEventListener("wheel", handleWheel);
    };
  }, [viewportRef]);
}
