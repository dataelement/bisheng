import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

const DEFAULT_WIDTH = 240;
const MIN_WIDTH = 200;
const MAX_WIDTH = 480;
const MIN_CONTENT_WIDTH = 360;
const WIDTH_KEY = "platform-knowledge-sidebar-width";

interface KnowledgeSidebarPaneProps {
  children: ReactNode;
}

function readWidth() {
  try {
    const saved = Number(window.localStorage.getItem(WIDTH_KEY));
    if (saved >= MIN_WIDTH && saved <= MAX_WIDTH) return Math.round(saved);
  } catch {
    // The divider still works when browser storage is unavailable.
  }
  return DEFAULT_WIDTH;
}

function clampWidth(width: number, maxWidth: number) {
  return Math.max(MIN_WIDTH, Math.min(maxWidth, Math.round(width)));
}

export function KnowledgeSidebarPane({ children }: KnowledgeSidebarPaneProps) {
  const { t } = useTranslation("knowledge");
  const paneId = useId();
  const paneRef = useRef<HTMLElement>(null);
  const drag = useRef<{ pointerId: number; x: number; width: number } | null>(null);
  const [preferredWidth, setPreferredWidth] = useState(readWidth);
  const [maxWidth, setMaxWidth] = useState(MAX_WIDTH);
  const [resizing, setResizing] = useState(false);
  const width = Math.min(preferredWidth, maxWidth);

  useEffect(() => {
    const workspace = paneRef.current?.parentElement;
    if (!workspace || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      setMaxWidth(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.floor(entry.contentRect.width) - MIN_CONTENT_WIDTH)));
    });
    observer.observe(workspace);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (resizing) return;
    try {
      window.localStorage.setItem(WIDTH_KEY, String(preferredWidth));
    } catch {
      // Persistence is optional.
    }
  }, [preferredWidth, resizing]);

  const handleResize = (next: number) => setPreferredWidth(clampWidth(next, maxWidth));
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || drag.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { pointerId: event.pointerId, x: event.clientX, width };
    setResizing(true);
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (start?.pointerId === event.pointerId) handleResize(start.width + event.clientX - start.x);
  };
  const handlePointerEnd = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    setResizing(false);
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    let next: number;
    switch (event.key) {
      case "ArrowLeft": next = width - 16; break;
      case "ArrowRight": next = width + 16; break;
      case "Home": next = MIN_WIDTH; break;
      case "End": next = maxWidth; break;
      default: return;
    }
    event.preventDefault();
    handleResize(next);
  };

  return (
    <>
      <aside
        id={paneId}
        ref={paneRef}
        className="flex h-full min-w-0 shrink-0 flex-col border-r-[0.5px] border-border-base bg-[#FBFBFB] pt-2 font-sans dark:bg-bg-page"
        style={{ width }}
        aria-label={t("f118.spaces")}
      >
        {children}
      </aside>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={t("sidebar.resize_navigation")}
        aria-controls={paneId}
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={maxWidth}
        aria-valuenow={width}
        tabIndex={0}
        data-resizing={resizing ? "true" : undefined}
        className="relative z-10 -mx-[3px] h-full w-[6px] shrink-0 cursor-col-resize touch-none select-none outline-none after:pointer-events-none after:absolute after:inset-y-0 after:left-1/2 after:w-0.5 after:-translate-x-1/2 hover:after:bg-text-2 focus-visible:after:bg-text-2 data-[resizing=true]:after:bg-text-2"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerEnd}
        onPointerCancel={handlePointerEnd}
        onLostPointerCapture={handlePointerEnd}
        onKeyDown={handleKeyDown}
        onDoubleClick={() => setPreferredWidth(DEFAULT_WIDTH)}
      />
    </>
  );
}
