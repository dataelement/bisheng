import { Tooltip } from '@bisheng/ui';
import { useEffect, useRef, useState } from 'react';

interface TruncatedTabLabelProps {
  name: string;
}

/** Reveal a sub-channel label only when the visible text is actually truncated. */
export function TruncatedTabLabel({ name }: TruncatedTabLabelProps) {
  const labelRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const el = labelRef.current;
    if (!el) return;
    const check = () => setIsTruncated(el.scrollWidth > el.clientWidth);
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [name]);
  return (
    <Tooltip open={open} onOpenChange={(next) => {
      if (next && !isTruncated) return;
      setOpen(next);
    }} content={name}>
      <span ref={labelRef} className="block max-w-[240px] truncate">{name}</span>
    </Tooltip>
  );
}
