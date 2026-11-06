import { useLayoutEffect, useState, type RefObject } from 'react';

/** Anchor the menu to the whole composer, including attached resources. */
export function useComposerMenuAnchor(trigger: RefObject<HTMLButtonElement>, open: boolean) {
  const [anchor, setAnchor] = useState({ width: 248, sideOffset: 4, alignOffset: 0 });
  useLayoutEffect(() => {
    if (!open) return;
    const button = trigger.current;
    const composer = button?.closest('.dsh-chat-composer');
    if (!button || !composer) return;
    const measure = () => {
      const bounds = composer.getBoundingClientRect();
      const control = button.getBoundingClientRect();
      setAnchor({
        width: bounds.width,
        sideOffset: control.top - bounds.top + 4,
        alignOffset: bounds.left - control.left,
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(composer);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [open, trigger]);
  return anchor;
}
