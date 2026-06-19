import {
  ChevronLeft,
  Glasses,
  Loader2,
  PaperclipIcon,
  SearchIcon,
} from "lucide-react";
import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  getMineSpacesApi,
  getJoinedSpacesApi,
  getDepartmentSpacesApi,
} from "~/api/knowledge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  Input
} from "~/components/ui";
import { Checkbox } from "~/components/ui/Checkbox";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "~/components/ui/Tooltip2";
import BookOpen from "~/components/ui/icon/BookOpen";
import BooksIcon from "~/components/ui/icon/Books";
import { useGetOrgToolList } from "~/hooks/queries/data-provider";
import { BsConfig } from "~/types/chat";
import { useLocalize, useMediaQuery, useScrollRevealRef } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";

// --- 类型定义 ---
export type KnowledgeType = 'org' | 'space';

export interface KnowledgeItem {
  id: string;
  name: string;
  type: KnowledgeType;
}

// --- Hooks ---
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

const MAX_SUB_HEIGHT = 240;
const BOTTOM_GAP = 8;
/** 移动端：碰撞检测余量；底部勿过大，否则 flip/shift 会把整块菜单顶到视口上方导致裁切 */
const MOBILE_MENU_COLLISION = {
  top: 56,
  bottom: 28,
  left: 12,
  right: 12,
} as const;

/**
 * Compute an alignOffset so the sub-content top aligns with the parent menu top,
 * and clamp maxH so the sub-content never overflows the viewport on either side.
 *
 * After the sub-content is rendered by Radix, we also observe its real position
 * and re-clamp maxH based on the actual top (handles Radix collision shifting).
 */
function useSubMenuLayout(menuRef: React.RefObject<HTMLDivElement | null>, triggerKey: string, open: boolean) {
  const [alignOffset, setAlignOffset] = useState(0);
  const [maxH, setMaxH] = useState<number>(MAX_SUB_HEIGHT);
  const subContentRef = useRef<HTMLElement | null>(null);

  // Phase 1 — compute alignOffset & an initial maxH from parent menu rect
  useLayoutEffect(() => {
    if (!open) return;

    const update = () => {
      const menuEl = menuRef.current;
      if (!menuEl) return;

      const menuRect = menuEl.getBoundingClientRect();

      const trigger = menuEl.querySelector<HTMLElement>(`[data-sub-key="${triggerKey}"]`);
      if (trigger) {
        const triggerRect = trigger.getBoundingClientRect();
        setAlignOffset(Math.round(menuRect.top - triggerRect.top));
      } else {
        setAlignOffset(0);
      }

      // Initial estimate — will be refined in Phase 2
      const spaceBelow = window.innerHeight - menuRect.top - BOTTOM_GAP;
      const spaceAbove = menuRect.bottom - BOTTOM_GAP;
      const available = Math.max(spaceBelow, spaceAbove);
      setMaxH(Math.min(Math.max(available, 120), MAX_SUB_HEIGHT));
    };

    requestAnimationFrame(update);
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [open, menuRef, triggerKey]);

  // Phase 2 — once Radix renders the actual sub-content, observe its real
  // position and clamp maxH so it stays within the viewport.
  useEffect(() => {
    if (!open) {
      subContentRef.current = null;
      return;
    }

    // Radix renders sub-content in a portal; locate it by role + data attribute
    const findSubContent = (): HTMLElement | null => {
      // Look for the sub-content element associated with this trigger
      const menuEl = menuRef.current;
      if (!menuEl) return null;

      const trigger = menuEl.querySelector<HTMLElement>(`[data-sub-key="${triggerKey}"]`);
      if (!trigger) return null;

      // The sub-content is rendered in a portal; we find it via the Radix
      // data-state="open" attribute on [role="menu"] elements in the document
      const allMenus = document.querySelectorAll<HTMLElement>('[role="menu"][data-state="open"]');
      // Pick the deepest nested one that is NOT the parent menu
      for (const m of Array.from(allMenus)) {
        if (m !== menuEl && !menuEl.contains(m)) {
          return m;
        }
      }
      return null;
    };

    const clampToViewport = () => {
      const el = subContentRef.current || findSubContent();
      if (!el) return;
      subContentRef.current = el;

      const rect = el.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.top - BOTTOM_GAP;
      const finalH = Math.min(Math.max(spaceBelow, 120), MAX_SUB_HEIGHT);
      setMaxH(finalH);
    };

    // Wait a tick for Radix portal to mount
    const rafId = requestAnimationFrame(() => {
      requestAnimationFrame(clampToViewport);
    });

    window.addEventListener('resize', clampToViewport);
    window.addEventListener('scroll', clampToViewport, true);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', clampToViewport);
      window.removeEventListener('scroll', clampToViewport, true);
    };
  }, [open, menuRef, triggerKey]);

  return { alignOffset, maxH };
}

// --- 子组件：列表面板 ---
const KnowledgeListPanel = ({
  placeholder,
  keyword,
  setKeyword,
  items,
  selectedItems, // 这里接收的是筛选后的数组
  onToggle,
  isFetching,
  hasMore,
  onLoadMore,
  emptyText,
}: {
  placeholder: string;
  keyword: string;
  setKeyword: (v: string) => void;
  items: any[];
  selectedItems: KnowledgeItem[];
  onToggle: (item: any) => void;
  isFetching: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  emptyText: string;
}) => {
  const listScrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
    if (scrollHeight - scrollTop <= clientHeight + 10 && !isFetching && hasMore) {
      onLoadMore();
    }
  };

  return (
    <div className="flex flex-col gap-1 min-h-0 flex-1">
      {/* 搜索框 */}
      <div className="relative shrink-0">
        <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
        <Input
          className="h-[28px] text-sm bg-white border border-[#ECECEC] rounded-[6px] pl-8 focus-visible:ring-1 focus-visible:ring-blue-500/20"
          placeholder={placeholder}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        />
      </div>

      {/* 滚动列表 */}
      <div
        ref={listScrollRevealRef}
        className="overflow-y-auto flex flex-col gap-0 scrollbar-on-scroll min-h-0 flex-1"
        onScroll={handleScroll}
      >
        {items.map((item) => {
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
              className="flex items-center gap-2 px-2 py-[5px] cursor-pointer rounded-[6px] data-[highlighted]:bg-[#f2f3f5] focus:bg-[#f2f3f5] outline-none transition-colors"
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

        {isFetching && (
          <div className="flex justify-center py-3">
            <Loader2 size={16} className="animate-spin text-slate-300" />
          </div>
        )}
        {!isFetching && items.length === 0 && (
          <div className="text-center text-[12px] text-slate-400 py-10">{emptyText}</div>
        )}
      </div>
    </div>
  );
};

// --- main ---
export const ChatKnowledge = ({
  variant = 'plus',
  config,
  disabled,
  value = [],
  onChange,
  showFileUpload = false,
  fileUploadDisabled = false,
  onFileUploadClick,
  showTaskModeEntry = false,
  onEnterTaskMode,
  renderSkillSubmenu,
  taskModeActive = false,
}: {
  /** Controls the trigger button and which menu sections render:
   *  - 'plus'      → "+" trigger; file-upload + task-mode (+ optional add-skill) sections.
   *  - 'knowledge' → pill trigger; knowledge-space + org-knowledge submenus only. */
  variant?: 'plus' | 'knowledge';
  config?: BsConfig;
  disabled: boolean;
  value: KnowledgeItem[];
  onChange: (val: KnowledgeItem[]) => void;
  /** Render a "上传文件" entry at the top of the menu (v2.5 plus menu). */
  showFileUpload?: boolean;
  fileUploadDisabled?: boolean;
  onFileUploadClick?: () => void;
  /** F035 (PRD §4.1.3): render the "任务模式" entry as a separate group at the
   *  bottom of the "+" menu. Daily chat → navigates to /linsight; routing is
   *  delegated to the caller so this component stays route-free. */
  showTaskModeEntry?: boolean;
  onEnterTaskMode?: () => void;
  /** F035: "添加 Skill" hover submenu (desktop) / drill panel (mobile); selecting a skill enters task mode. */
  renderSkillSubmenu?: (close: () => void) => ReactNode;
  /** When already in task mode, show the entry checked (toggle indicator). */
  taskModeActive?: boolean;
}) => {
  const localize = useLocalize();
  const PAGE_SIZE = 20;
  const MAX_KB_PER_TYPE = 50;
  const { showToast } = useToastContext();

  // checked data
  const selectedKnowledgeSpaces = useMemo(
    () => value.filter((item) => item.type === 'space'),
    [value]
  );

  const selectedOrgKbs = useMemo(
    () => value.filter((item) => item.type === 'org'),
    [value]
  );

  // search page
  const [orgKeyword, setOrgKeyword] = useState("");
  const debouncedOrgKeyword = useDebounce(orgKeyword, 500);
  const [orgPage, setOrgPage] = useState(1);
  const [allOrgKbs, setAllOrgKbs] = useState<any[]>([]);
  const [hasMoreOrg, setHasMoreOrg] = useState(true);

  // --- Knowledge space data (load all on mount, no pagination) ---
  const [spaceKeyword, setSpaceKeyword] = useState("");
  const debouncedSpaceKeyword = useDebounce(spaceKeyword, 300);
  const [allSpaces, setAllSpaces] = useState<any[]>([]);
  const [spaceFetching, setSpaceFetching] = useState(false);

  const loadSpaces = useCallback(async () => {
    setSpaceFetching(true);
    try {
      // Fetch "mine" + "joined" + "department" in parallel and merge into a single list
      const [mine, joined, department] = await Promise.all([
        getMineSpacesApi(),
        getJoinedSpacesApi(),
        getDepartmentSpacesApi(),
      ]);
      // Dedupe by id (a space could in principle appear in more than one list)
      const seen = new Set<string | number>();
      const merged: any[] = [];
      for (const s of [...mine, ...joined, ...department]) {
        if (seen.has(s.id)) continue;
        seen.add(s.id);
        merged.push(s);
      }
      // Sort A–Z, English (ASCII-leading) names first, then Chinese names.
      // Within each bucket, compare with the appropriate locale so that
      // pinyin order is used for CJK and natural order for ASCII.
      merged.sort((a, b) => {
        const an = (a.name || "").trim();
        const bn = (b.name || "").trim();
        const aIsEn = an.length > 0 && an.charCodeAt(0) < 128;
        const bIsEn = bn.length > 0 && bn.charCodeAt(0) < 128;
        if (aIsEn !== bIsEn) return aIsEn ? -1 : 1;
        return an.localeCompare(bn, aIsEn ? "en" : "zh-Hans-u-co-pinyin", {
          sensitivity: "base",
        });
      });
      setAllSpaces(merged);
    } catch (err) {
      console.error("[ChatKnowledge] Failed to load spaces:", err);
    } finally {
      setSpaceFetching(false);
    }
  }, []);

  // Spaces are only shown inside the open picker, so load them lazily on first
  // open (and refresh on each reopen) instead of eagerly on mount. The eager
  // mount-fetch fired knowledge/space/{mine,joined} every time the input box
  // re-mounted (e.g. the send-triggered welcome→messages layout flip), causing
  // duplicate requests on send.
  const [rootOpen, setRootOpen] = useState(false);
  useEffect(() => {
    if (rootOpen) loadSpaces();
  }, [rootOpen, loadSpaces]);

  // Client-side filter by keyword
  const filteredSpaces = useMemo(
    () =>
      debouncedSpaceKeyword
        ? allSpaces.filter((s) =>
          s.name?.toLowerCase().includes(debouncedSpaceKeyword.toLowerCase())
        )
        : allSpaces,
    [allSpaces, debouncedSpaceKeyword]
  );

  // Comma-separated ids of admin-configured org KBs. Passed to the backend so
  // those ids are floated to the top of the global sort — otherwise a
  // configured KB sitting on page 2+ of the alpha list could never be promoted
  // by client-side reshuffle alone.
  const preferredIds = useMemo(() => {
    const configured = (config as any)?.orgKbs || [];
    if (!configured.length) return '';
    return configured.map((k: any) => String(k.id)).join(',');
  }, [config]);

  // Org KB data fetching (paginated via react-query)
  const { data: orgData, isFetching: orgFetching } = useGetOrgToolList({
    page: orgPage,
    page_size: PAGE_SIZE,
    name: debouncedOrgKeyword,
    sort_by: 'name',
    preferred_ids: preferredIds,
  });

  useEffect(() => {
    setOrgPage(1);
    setAllOrgKbs([]);
  }, [debouncedOrgKeyword, preferredIds]);

  useEffect(() => {
    if (orgData) {
      setAllOrgKbs((prev) => (orgPage === 1 ? [...orgData] : [...prev, ...orgData]));
      setHasMoreOrg(orgData.length === PAGE_SIZE);
    }
  }, [orgData, orgPage]);

  // Sort: admin-configured org KBs (in sort_order) first, then any other KBs
  // the user can access. Filtering by use-permission is enforced server-side
  // in useGetOrgToolList — we only reshuffle display order here.
  const sortedOrgKbs = useMemo(() => {
    const configured = (config as any)?.orgKbs || [];
    if (!configured.length) return allOrgKbs;
    const ordered = [...configured].sort((a: any, b: any) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
    const configuredIds = new Set(ordered.map((k: any) => String(k.id)));
    const byId = new Map(allOrgKbs.map((k: any) => [String(k.id), k]));
    const head = ordered
      .map((k: any) => byId.get(String(k.id)))
      .filter(Boolean);
    const tail = allOrgKbs.filter((k: any) => !configuredIds.has(String(k.id)));
    return [...head, ...tail];
  }, [allOrgKbs, config]);

  // checked data — compare with String() on both sides (API returns numeric
  // ids, but the atom type + default-seeding use strings).
  const handleToggle = (item: any, type: KnowledgeType) => {
    const itemKey = String(item.id);
    const exists = value.some((i) => String(i.id) === itemKey && i.type === type);

    if (exists) {
      const nextValue = value.filter((i) => !(String(i.id) === itemKey && i.type === type));
      onChange(nextValue);
    } else {
      const currentTypeCount = value.filter(i => i.type === type).length;

      if (currentTypeCount >= MAX_KB_PER_TYPE) {
        showToast({
          message:
            type === 'space'
              ? localize('com_chat_knowledge_toast_space_limit')
              : localize('com_chat_knowledge_toast_org_limit'),
          status: 'error',
        });
        return;
      }

      // Normalise id to string on insert to keep the atom invariant stable.
      const newItem: KnowledgeItem = { id: itemKey, name: item.name, type };
      onChange([newItem, ...value]);
    }
  };

  const hasAnySelection = value.length > 0;
  const orgEnabled = !!config?.knowledgeBase?.enabled;

  const [openSub, setOpenSub] = useState<'org' | null>(null);
  // 仅 <=576 走移动端下钻面板；577~768 保持桌面级联交互（右侧展开）
  const isMobile = useMediaQuery('(max-width: 576px)');
  const [mobilePanel, setMobilePanel] = useState<'root' | 'org' | 'skill'>('root');
  const menuContentRef = useRef<HTMLDivElement>(null);
  const orgLayout = useSubMenuLayout(menuContentRef, 'org', openSub === 'org');

  const handleRootOpenChange = useCallback((open: boolean) => {
    setRootOpen(open);
    setOpenSub(null);
    setMobilePanel('root');
  }, []);

  const triggerRef = useRef<HTMLButtonElement | null>(null);
  /** 第二层：高度取触发器上下可用空间的较小值，避免翻转到上方后仍按「很高」排版导致顶出屏幕 */
  const [mobileDrillMaxH, setMobileDrillMaxH] = useState<number | undefined>(undefined);
  const [mobileMenuSide, setMobileMenuSide] = useState<'top' | 'bottom'>('bottom');

  // A "tall list panel" needs the adaptive height cap on mobile: the knowledge
  // pill always shows the spaces list directly, and the "+" menu shows the org
  // list once drilled into ('org'). The "+" root (short action items) does not.
  const mobileTallPanel = variant === 'knowledge' || mobilePanel !== 'root';

  useLayoutEffect(() => {
    if (!isMobile || !rootOpen || !mobileTallPanel) {
      setMobileDrillMaxH(undefined);
      setMobileMenuSide('bottom');
      return;
    }
    const run = () => {
      const el = triggerRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const padT = MOBILE_MENU_COLLISION.top;
      const padB = MOBILE_MENU_COLLISION.bottom;
      const above = r.top - padT;
      const below = window.innerHeight - r.bottom - padB;
      // Mobile adaptive strategy:
      // prefer opening downward when there is enough space;
      // otherwise open upward to avoid being clipped by the chat input area.
      const preferBottom = below >= 240 || below >= above;
      setMobileMenuSide(preferBottom ? 'bottom' : 'top');
      const raw = (preferBottom ? below : above) - 8;
      const capped = Math.min(Math.max(Math.floor(raw), 80), Math.floor(window.innerHeight * 0.72));
      setMobileDrillMaxH(capped);
    };
    run();
    const ro = new ResizeObserver(run);
    if (triggerRef.current) ro.observe(triggerRef.current);
    window.addEventListener('resize', run);
    window.addEventListener('scroll', run, true);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', run);
      window.removeEventListener('scroll', run, true);
    };
  }, [isMobile, rootOpen, mobileTallPanel]);

  return (
    <DropdownMenu open={rootOpen} onOpenChange={handleRootOpenChange}>
      <TooltipProvider delayDuration={50}>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild disabled={disabled}>
              {variant === 'knowledge' ? (
                <button
                  ref={triggerRef}
                  type="button"
                  className={cn(
                    "flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-[13px] font-normal text-[#4E5969] outline-none transition-colors hover:bg-[#f8f8f8]",
                    disabled && "opacity-50 cursor-not-allowed hover:bg-transparent"
                  )}
                  aria-label={localize('com_ui_knowledge_space')}
                >
                  <div className="relative shrink-0">
                    <span
                      aria-hidden
                      className="block size-4 bg-[#165DFF]"
                      style={{
                        WebkitMaskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/book-one.svg)`,
                        maskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/book-one.svg)`,
                        WebkitMaskRepeat: 'no-repeat', maskRepeat: 'no-repeat',
                        WebkitMaskPosition: 'center', maskPosition: 'center',
                        WebkitMaskSize: 'contain', maskSize: 'contain',
                      }}
                    />
                    {selectedKnowledgeSpaces.length > 0 && (
                      <span className="absolute -right-1 -top-1 size-2.5 rounded-full border-2 border-white bg-blue-500" />
                    )}
                  </div>
                  <span>{localize('com_ui_knowledge_space')}</span>
                  <Outlined.Down size={16} className="text-[#999]" />
                </button>
              ) : (
                <button
                  ref={triggerRef}
                  type="button"
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-md text-[#4E5969] cursor-pointer hover:bg-[#f8f8f8] transition-colors outline-none",
                    disabled && "opacity-50 cursor-not-allowed"
                  )}
                  aria-label={localize('com_knowledge_add_file')}
                >
                  <Outlined.Plus size={18} />
                </button>
              )}
            </DropdownMenuTrigger>
          </TooltipTrigger>
          {/* The knowledge pill already shows its label inline, so it needs no
              tooltip; only the icon-only "+" trigger gets one. */}
          {variant !== 'knowledge' && (
            <TooltipContent side="bottom" sideOffset={6}>
              {localize('com_knowledge_add_file')}
            </TooltipContent>
          )}
        </Tooltip>
      </TooltipProvider>

      <DropdownMenuContent
        ref={menuContentRef}
        align="start"
        side={isMobile ? mobileMenuSide : 'bottom'}
        collisionPadding={isMobile ? MOBILE_MENU_COLLISION : BOTTOM_GAP}
        sticky={isMobile ? 'partial' : undefined}
        onCloseAutoFocus={(e) => e.preventDefault()}
        className={cn(
          'flex flex-col gap-0 rounded-[8px] border-0 shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]',
          // variant-aware width/padding: the pill (knowledge) shows a list
          // directly, so it needs the wider list layout; the "+" menu stays
          // compact for its short action items.
          variant === 'knowledge'
            ? 'w-[240px] overflow-hidden p-2'
            : 'w-[200px] p-2',
          isMobile && 'touch-mobile:w-[min(calc(100vw-24px),320px)] touch-mobile:p-2',
          isMobile &&
          mobileTallPanel &&
          'touch-mobile:min-h-0 touch-mobile:overflow-hidden',
        )}
        style={
          isMobile && mobileTallPanel && mobileDrillMaxH !== undefined
            ? { maxHeight: mobileDrillMaxH }
            : // Desktop knowledge pill: cap height so the space list scrolls
              // internally instead of growing past the viewport.
              !isMobile && variant === 'knowledge'
              ? { maxHeight: MAX_SUB_HEIGHT }
              : undefined
        }
      >
        {variant === 'plus' && showFileUpload && ((!isMobile) || (isMobile && mobilePanel === 'root')) && (
          <DropdownMenuItem
            disabled={fileUploadDisabled}
            onSelect={(e) => {
              e.preventDefault();
              if (fileUploadDisabled) return;
              onFileUploadClick?.();
            }}
            className="flex cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] outline-none data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40"
          >
            <Outlined.Attachment size={18} className="text-[#999]" />
            <span className="text-[14px] font-normal text-slate-700">{localize('com_ui_upload_files')}</span>
          </DropdownMenuItem>
        )}

        {/* Knowledge pill (mobile): show the SPACES list directly — no drill. */}
        {variant === 'knowledge' && isMobile && (
          <div className="flex min-h-0 w-full flex-1 flex-col gap-2">
            <KnowledgeListPanel
              placeholder={localize('com_chat_knowledge_placeholder_search_space')}
              keyword={spaceKeyword}
              setKeyword={setSpaceKeyword}
              items={filteredSpaces}
              selectedItems={selectedKnowledgeSpaces}
              onToggle={(item) => handleToggle(item, 'space')}
              isFetching={spaceFetching}
              hasMore={false}
              onLoadMore={() => { }}
              emptyText={localize('com_chat_knowledge_empty_no_spaces')}
            />
          </div>
        )}

        {/* Knowledge pill (desktop): show the SPACES list directly — no sub. */}
        {variant === 'knowledge' && !isMobile && (
          <div className="flex min-h-0 w-full flex-1 flex-col">
            <p className="mb-1 shrink-0 px-2 py-[5px] text-[14px] font-medium leading-[22px] text-[#1A1A1A]">
              {localize('com_ui_knowledge_space')}
            </p>
            <KnowledgeListPanel
              placeholder={localize('com_chat_knowledge_placeholder_search_space')}
              keyword={spaceKeyword}
              setKeyword={setSpaceKeyword}
              items={filteredSpaces}
              selectedItems={selectedKnowledgeSpaces}
              onToggle={(item) => handleToggle(item, 'space')}
              isFetching={spaceFetching}
              hasMore={false}
              onLoadMore={() => { }}
              emptyText={localize('com_chat_knowledge_empty_no_spaces')}
            />
          </div>
        )}

        {/* Org knowledge selector — moved into the "+" menu, below upload.
            Desktop: cascading submenu. Gated by KB feature flag. */}
        {variant === 'plus' && !isMobile && config?.knowledgeBase?.enabled !== false && (
          <DropdownMenuSub
            open={openSub === 'org'}
            onOpenChange={(o) => {
              if (o) setOpenSub('org');
              else setOpenSub((cur) => (cur === 'org' ? null : cur));
            }}
          >
            <DropdownMenuSubTrigger
              data-sub-key="org"
              className={cn(
                'mt-0.5 flex cursor-pointer items-center justify-between rounded-[6px] px-2 py-[5px] outline-none',
              )}
            >
              <div className="flex items-center gap-2">
                <div className="relative">
                  <Outlined.Books size={18} className="text-[#999]" />
                  {selectedOrgKbs.length > 0 && (
                    <span className="absolute -right-1 -top-1 size-2.5 rounded-full border-2 border-white bg-blue-500" />
                  )}
                </div>
                <span className="text-[14px] font-normal text-slate-700">
                  {localize('com_tools_org_knowledge')}
                </span>
              </div>
            </DropdownMenuSubTrigger>

            <DropdownMenuSubContent
              alignOffset={orgLayout.alignOffset}
              collisionPadding={BOTTOM_GAP}
              className="ml-2 flex w-[240px] flex-col overflow-hidden rounded-[8px] border-slate-100 bg-white p-2 shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]"
              style={
                {
                  '--tw-enter-duration': '0.35s',
                  '--tw-enter-easing': 'ease-in-out',
                  maxHeight: orgLayout.maxH,
                } as React.CSSProperties
              }
            >
              <p className="mb-1 shrink-0 px-2 py-[5px] text-[14px] font-medium leading-[22px] text-[#1A1A1A]">
                {localize('com_tools_org_knowledge')}
              </p>
              <KnowledgeListPanel
                placeholder={localize('com_tools_knowledge_base_search')}
                keyword={orgKeyword}
                setKeyword={setOrgKeyword}
                items={sortedOrgKbs}
                selectedItems={selectedOrgKbs}
                onToggle={(item) => handleToggle(item, 'org')}
                isFetching={orgFetching}
                hasMore={hasMoreOrg}
                onLoadMore={() => setOrgPage((p) => p + 1)}
                emptyText={localize('com_chat_knowledge_empty_no_org_kbs')}
              />
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}

        {/* Org knowledge selector (mobile): drill option on the "+" root. */}
        {variant === 'plus' && isMobile && mobilePanel === 'root' && config?.knowledgeBase?.enabled !== false && (
          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault();
              setMobilePanel('org');
            }}
            className="mt-0.5 flex cursor-pointer items-center justify-between gap-2 rounded-[6px] px-2 py-[5px] outline-none"
          >
            <div className="flex min-w-0 items-center gap-2">
              <div className="relative shrink-0">
                <Outlined.Books size={18} className="text-[#999]" />
                {selectedOrgKbs.length > 0 && (
                  <span className="absolute -right-1 -top-1 size-2.5 rounded-full border-2 border-white bg-blue-500" />
                )}
              </div>
              <span className="truncate text-[14px] font-normal text-slate-700">
                {localize('com_tools_org_knowledge')}
              </span>
            </div>
            <Outlined.Right className="size-4 shrink-0 text-slate-400" />
          </DropdownMenuItem>
        )}

        {/* Org knowledge selector (mobile): drill panel. */}
        {variant === 'plus' && isMobile && mobilePanel === 'org' && config?.knowledgeBase?.enabled !== false && (
          <div className="flex min-h-0 w-full flex-1 flex-col gap-2">
            <div className="flex shrink-0 items-center gap-0.5 border-b border-slate-100 pb-2">
              <button
                type="button"
                className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100"
                aria-label={localize('com_ui_go_back')}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setMobilePanel('root');
                }}
              >
                <ChevronLeft className="size-5" strokeWidth={2} />
              </button>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
                {localize('com_tools_org_knowledge')}
              </span>
            </div>
            <KnowledgeListPanel
              placeholder={localize('com_tools_knowledge_base_search')}
              keyword={orgKeyword}
              setKeyword={setOrgKeyword}
              items={sortedOrgKbs}
              selectedItems={selectedOrgKbs}
              onToggle={(item) => handleToggle(item, 'org')}
              isFetching={orgFetching}
              hasMore={hasMoreOrg}
              onLoadMore={() => setOrgPage((p) => p + 1)}
              emptyText={localize('com_chat_knowledge_empty_no_org_kbs')}
            />
          </div>
        )}

        {/* F035 (PRD §4.1.3) — 任务模式组：以分隔线与上方通用上下文组隔开。
            桌面端与移动端 root 面板都展示；进入任务模式跳转 /linsight。 */}
        {variant === 'plus' && showTaskModeEntry && ((!isMobile) || (isMobile && mobilePanel === 'root')) && (
          <>
            <div className="my-1 h-px bg-slate-100" />
            <DropdownMenuItem
              onSelect={() => {
                // Close the menu before navigating: keeping it open while the
                // trigger unmounts on route change leaves the popover anchorless
                // and it jumps to the top-left corner.
                setRootOpen(false);
                onEnterTaskMode?.();
              }}
              className="flex cursor-pointer items-center gap-2 rounded-[6px] px-2 py-[5px] outline-none"
            >
              <Outlined.Binoculars size={18} className={taskModeActive ? 'text-blue-600' : 'text-[#999]'} />
              <span className={cn('flex-1 text-[14px] font-normal', taskModeActive ? 'text-blue-600' : 'text-slate-700')}>
                {localize('com_linsight_task_mode')}
              </span>
              {taskModeActive && <Outlined.Check size={14} className="text-blue-600" />}
            </DropdownMenuItem>
            {/* 添加 Skill — 桌面：悬停展开技能选择器；移动 root：下钻进技能面板。
                选中技能即进入任务模式（由 renderSkillSubmenu 内部导航），故传入
                close 让选择器先关掉「+」菜单，避免 popover 跳位。 */}
            {renderSkillSubmenu && (
              !isMobile ? (
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger
                    className={cn(
                      'flex cursor-pointer items-center justify-between rounded-[6px] px-2 py-[5px] outline-none',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Outlined.Newspaper size={18} className="text-[#999]" />
                      <span className="text-[14px] font-normal text-slate-700">
                        {localize('com_linsight_add_skill')}
                      </span>
                    </div>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent className="ml-2 flex max-h-[360px] w-[280px] flex-col overflow-hidden rounded-2xl border-slate-100 bg-white p-3 shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]">
                    {renderSkillSubmenu(() => setRootOpen(false))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              ) : (
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault();
                    setMobilePanel('skill');
                  }}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded-[6px] px-2 py-[5px] outline-none"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <Outlined.Newspaper size={18} className="text-[#999]" />
                    <span className="truncate text-[14px] font-normal text-slate-700">
                      {localize('com_linsight_add_skill')}
                    </span>
                  </div>
                  <Outlined.Right className="size-4 shrink-0 text-slate-400" />
                </DropdownMenuItem>
              )
            )}
          </>
        )}

        {/* 添加 Skill — 移动端下钻面板 */}
        {isMobile && mobilePanel === 'skill' && renderSkillSubmenu && (
          <div className="flex min-h-0 w-full flex-1 flex-col gap-2">
            <div className="flex shrink-0 items-center gap-0.5 border-b border-slate-100 pb-2">
              <button
                type="button"
                className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-slate-600 hover:bg-slate-100"
                aria-label={localize('com_ui_go_back')}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setMobilePanel('root');
                }}
              >
                <ChevronLeft className="size-5" strokeWidth={2} />
              </button>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
                {localize('com_linsight_add_skill')}
              </span>
            </div>
            {renderSkillSubmenu(() => setRootOpen(false))}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};