/**
 * Search box + scrollable multi-select list used by the knowledge pickers in
 * the chat input toolbar.
 *
 * Two shapes:
 *  - flat (`items`)  — organization knowledge bases, server-paginated;
 *  - grouped (`groups`) — knowledge spaces, split into 部门知识空间 / 我创建的 /
 *    我加入的. Callers drop empty groups before passing them in, so a group
 *    title never renders without rows underneath it.
 */
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { DropdownMenuItem } from "~/components/ui";
import { Checkbox } from "~/components/ui/Checkbox";
import { SearchInput, StateView } from "@bisheng/ui";
import { useLocalize, useScrollRevealRef } from "~/hooks";
import { cn } from "~/utils";
import type { KnowledgeItem } from "./knowledgeTypes";

/** The only fields a picker row needs; both knowledge spaces and org KBs satisfy it. */
export interface KnowledgeListItem {
  id: string | number;
  name?: string;
}

export interface KnowledgeListGroup {
  key: string;
  label: string;
  items: KnowledgeListItem[];
}

interface KnowledgeListPanelProps {
  placeholder: string;
  keyword: string;
  setKeyword: (v: string) => void;
  /** Flat list. Ignored when `groups` is supplied. */
  items?: KnowledgeListItem[];
  /** Titled sections, rendered in the given order. */
  groups?: KnowledgeListGroup[];
  selectedItems: KnowledgeItem[];
  onToggle: (item: KnowledgeListItem) => void;
  isFetching: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  emptyText: string;
  /** Hold the list at its unfiltered height while a keyword is active, so a
   *  centre-aligned panel doesn't jump as results shrink. Opt-in: only the
   *  panels that are vertically centred on their trigger need it. */
  freezeHeightOnFilter?: boolean;
}

export const KnowledgeListPanel = ({
  placeholder,
  keyword,
  setKeyword,
  items,
  groups,
  selectedItems, // 这里接收的是筛选后的数组
  onToggle,
  isFetching,
  hasMore,
  onLoadMore,
  emptyText,
  freezeHeightOnFilter = false,
}: KnowledgeListPanelProps) => {
  const localize = useLocalize();
  const listScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  // Direct ref to the scroll container so we can read scroll metrics for the
  // edge-shadow indicators (useScrollRevealRef is callback-only and only
  // toggles a `data-scrolling` attribute).
  const scrollNodeRef = useRef<HTMLDivElement | null>(null);
  const setScrollRefs = useCallback(
    (node: HTMLDivElement | null) => {
      scrollNodeRef.current = node;
      listScrollRevealRef(node);
    },
    [listScrollRevealRef],
  );

  // Grouped and flat callers share one render path: a flat list is just a
  // single untitled section.
  const sections = useMemo<Array<{ key: string; label?: string; items: KnowledgeListItem[] }>>(
    () => groups ?? [{ key: "__flat__", items: items ?? [] }],
    [groups, items],
  );
  const totalCount = useMemo(
    () => sections.reduce((sum, section) => sum + section.items.length, 0),
    [sections],
  );

  // Filtering shrinks the list; on a panel that is centred on its trigger that
  // reads as the panel jumping. Sample the unfiltered height and hold it as a
  // floor while a keyword is active.
  const listAreaRef = useRef<HTMLDivElement | null>(null);
  const [unfilteredHeight, setUnfilteredHeight] = useState<number>();
  useLayoutEffect(() => {
    if (!freezeHeightOnFilter || keyword) return; // only the unfiltered list is a valid sample
    const el = listAreaRef.current;
    if (el) setUnfilteredHeight(el.getBoundingClientRect().height);
  }, [freezeHeightOnFilter, keyword, totalCount]);

  // Edge shadows: visible only when there is content above / below the current
  // viewport. Shadows fade out at the top/bottom boundary.
  const [canScrollUp, setCanScrollUp] = useState(false);
  const [canScrollDown, setCanScrollDown] = useState(false);
  const updateScrollIndicators = useCallback(() => {
    const el = scrollNodeRef.current;
    if (!el) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    setCanScrollUp(scrollTop > 0);
    setCanScrollDown(scrollTop + clientHeight < scrollHeight - 1);
  }, []);
  useEffect(() => {
    updateScrollIndicators();
  }, [totalCount, updateScrollIndicators]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
    if (scrollHeight - scrollTop <= clientHeight + 10 && !isFetching && hasMore) {
      onLoadMore();
    }
    updateScrollIndicators();
  };

  return (
    // gap-2: 8px between the search box and the list below it, so the first row
    // doesn't crowd the input's bottom border (matches the skill panel).
    <div className="flex flex-col gap-2 min-h-0 flex-1">
      {/* 搜索框 — spec SearchInput. stopPropagation lives on the wrapper so a
          click ANYWHERE in the shell (magnifier, padding, clear) stays out of
          the Radix menu's type-ahead / close logic, not just clicks on the
          <input> itself. */}
      <div
        className="shrink-0"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <SearchInput
          placeholder={placeholder}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          clearLabel={localize("com_ui_clear")}
        />
      </div>

      {/* 滚动列表 — wrapped in a relative container so the top/bottom edge
          shadows can be absolutely positioned over the scroll viewport. */}
      <div
        ref={listAreaRef}
        className="relative flex min-h-0 flex-1 flex-col"
        style={freezeHeightOnFilter && keyword ? { minHeight: unfilteredHeight } : undefined}
      >
        {/* Top edge fade — solid popup-white fades to transparent so list
            content visually dissolves into the menu surface. */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute left-0 right-0 top-0 h-3 z-10 transition-opacity duration-150",
            "bg-gradient-to-b from-white to-transparent",
            canScrollUp ? "opacity-100" : "opacity-0",
          )}
        />
        {/* Bottom edge fade — same idea, mirrored. */}
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute bottom-0 left-0 right-0 h-3 z-10 transition-opacity duration-150",
            "bg-gradient-to-t from-white to-transparent",
            canScrollDown ? "opacity-100" : "opacity-0",
          )}
        />
        <div
          ref={setScrollRefs}
          className="overflow-y-auto flex flex-col gap-1 scrollbar-on-scroll min-h-0 flex-1 pb-3"
          onScroll={handleScroll}
        >
          {sections.map((section) => (
            <div key={section.key} className="flex flex-col">
              {section.label && (
                <p className="px-2 pb-0.5 pt-1.5 text-caption text-text-3">{section.label}</p>
              )}
              {section.items.map((item) => {
                // 判断是否选中 — coerce both sides to string: list items arrive from
                // API as numeric ids, while selected items may be strings (defaults
                // seeded via `String(k.id)` or restored from localStorage).
                const isChecked = selectedItems.some((s) => String(s.id) === String(item.id));
                return (
                  <DropdownMenuItem
                    key={item.id}
                    onSelect={(e) => {
                      e.preventDefault();
                      onToggle(item);
                    }}
                    className="flex h-8 items-center gap-2 px-2 cursor-pointer rounded-lg data-[highlighted]:bg-fill-2 focus:bg-fill-2 outline-none transition-colors"
                  >
                    <Checkbox
                      checked={isChecked}
                      tabIndex={-1}
                      className="pointer-events-none shrink-0 border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                    />
                    <span className="truncate flex-1 text-[14px] text-slate-700 leading-[22px]">
                      {item.name}
                    </span>
                  </DropdownMenuItem>
                );
              })}
            </div>
          ))}

          {isFetching && (
            <div className="flex justify-center py-3">
              <Loader2 size={16} className="animate-spin text-slate-300" />
            </div>
          )}
          {!isFetching && totalCount === 0 && (
            // Inline tier (组件-State状态页.md §3): a selector with no options
            // gets one centered line and no artwork. Fills the scroll viewport
            // so the copy sits in the panel's middle rather than stranded under
            // the search box.
            <div className="flex min-h-0 flex-1 items-center justify-center">
              <StateView size="inline" title={emptyText} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

KnowledgeListPanel.displayName = "KnowledgeListPanel";
