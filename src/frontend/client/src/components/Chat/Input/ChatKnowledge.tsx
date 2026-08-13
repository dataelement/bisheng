import {
  ChevronLeft,
  Glasses,
  PaperclipIcon,
} from "lucide-react";
import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "~/components/ui";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "~/components/ui/Tooltip2";
import BookOpen from "~/components/ui/icon/BookOpen";
import BooksIcon from "~/components/ui/icon/Books";
import { useGetOrgToolList } from "~/hooks/queries/data-provider";
import { BsConfig } from "~/types/chat";
import { useCategorizedKnowledgeSpaces, useLocalize, useMediaQuery } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";
import { KnowledgeListPanel } from "./KnowledgeListPanel";
import type { KnowledgeItem, KnowledgeType } from "./knowledgeTypes";

export type { KnowledgeItem, KnowledgeType } from "./knowledgeTypes";

// --- Hooks ---
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

const MAX_SUB_HEIGHT = 256;
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
  onFolderUploadClick,
  showTaskModeEntry = false,
  onEnterTaskMode,
  renderSkillSubmenu,
  taskModeActive = false,
  skillSelected = false,
  compact = false,
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
  /** Render an "上传文件夹" entry below it. Task mode only — omit to hide it. */
  onFolderUploadClick?: () => void;
  /** F035 (PRD §4.1.3): render the "任务模式" entry as a separate group at the
   *  bottom of the "+" menu. Daily chat → navigates to /linsight; routing is
   *  delegated to the caller so this component stays route-free. */
  showTaskModeEntry?: boolean;
  onEnterTaskMode?: () => void;
  /** F035: "添加 Skill" hover submenu (desktop) / drill panel (mobile); selecting a skill enters task mode. */
  renderSkillSubmenu?: (close: () => void) => ReactNode;
  /** When already in task mode, show the entry checked (toggle indicator). */
  taskModeActive?: boolean;
  /** F035: tint the "添加技能" icon brand-blue once at least one skill is picked. */
  skillSelected?: boolean;
  /** Toolbar out of room (see useContainerCompact): collapse label to icon. */
  compact?: boolean;
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

  // --- Knowledge space data (load all groups at once, no pagination) ---
  const [spaceKeyword, setSpaceKeyword] = useState("");
  const debouncedSpaceKeyword = useDebounce(spaceKeyword, 300);

  // Spaces are only shown inside the open picker, so load them lazily on first
  // open instead of eagerly on mount. The eager mount-fetch fired
  // knowledge/space/{mine,joined} every time the input box re-mounted (e.g. the
  // send-triggered welcome→messages layout flip), causing duplicate requests on send.
  const [rootOpen, setRootOpen] = useState(false);

  // Grouped as 部门知识空间 / 我创建的 / 我加入的, matching the 知识空间 page.
  // Empty groups (including "no search hit in this group") are dropped by the hook.
  const { groups: spaceGroups, isFetching: spaceFetching } = useCategorizedKnowledgeSpaces({
    enabled: rootOpen,
    keyword: debouncedSpaceKeyword,
  });
  const spaceListGroups = useMemo(
    () => spaceGroups.map((group) => ({ key: group.key, label: group.label, items: group.spaces })),
    [spaceGroups],
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
      // Fixed cap aligned with the desktop popup (MAX_SUB_HEIGHT = 256), but
      // fall back to whatever space is actually available on the chosen side if
      // 256 wouldn't fit — keeps the popup from being clipped against the
      // viewport edge on smaller phones.
      const raw = (preferBottom ? below : above) - 8;
      const capped = Math.min(MAX_SUB_HEIGHT, Math.max(80, Math.floor(raw)));
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
                    // `group` lets the chevron pick up the Radix-emitted
                    // `data-state` to mirror the Tools-select rotation.
                    "group flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-2 text-[14px] font-normal text-[#4E5969] outline-none transition-colors hover:bg-[#f8f8f8]",
                    disabled && "opacity-50 cursor-not-allowed hover:bg-transparent"
                  )}
                  aria-label={localize('com_ui_knowledge_space')}
                >
                  <div className="relative shrink-0">
                    {/* Icon is neutral by default (matches the + button) and
                        turns brand-blue once a space is selected. */}
                    <span
                      aria-hidden
                      className={cn(
                        "block size-4",
                        selectedKnowledgeSpaces.length > 0 ? "bg-blue-500" : "bg-[#999999]"
                      )}
                      style={{
                        WebkitMaskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/book-one.svg)`,
                        maskImage: `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/book-one.svg)`,
                        WebkitMaskRepeat: 'no-repeat', maskRepeat: 'no-repeat',
                        WebkitMaskPosition: 'center', maskPosition: 'center',
                        WebkitMaskSize: 'contain', maskSize: 'contain',
                      }}
                    />
                  </div>
                  {/* Compact: collapse to icon + chevron only to save
                      horizontal space in the input toolbar. */}
                  {!compact && <span>{localize('com_ui_knowledge_space')}</span>}
                  <Outlined.Down size={16} className={cn("text-[#999] transition-transform duration-200", rootOpen && "rotate-180")} />
                </button>
              ) : (
                <button
                  ref={triggerRef}
                  type="button"
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-lg text-[#4E5969] cursor-pointer hover:bg-[#f8f8f8] transition-colors outline-none",
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
          'flex flex-col gap-0 rounded-lg border-0 shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]',
          // variant-aware width/padding: the pill (knowledge) shows a list
          // directly, so it needs the wider list layout; the "+" menu stays
          // compact for its short action items.
          variant === 'knowledge'
            ? 'w-[240px] overflow-hidden pt-2 px-2 pb-0'
            : 'w-[160px] p-2',
          // Mobile width override only applies to the knowledge variant — the
          // "+" menu shows short action items and matches the desktop 160px
          // width on phones too. (knowledge needs more room for search + list)
          // Mobile: any "tall" panel (knowledge, or the "+" menu drilled into
          // skill / org lists) needs the wider width; 160px is fine only for
          // the compact root of the "+" menu (short action items).
          isMobile && mobileTallPanel && 'touch-mobile:w-[min(calc(100vw-24px),320px)]',
          // Mobile knowledge popup only: replace `p-2` with `pt-2 px-2 pb-0` so
          // the scroll list's own `pb-2` handles the last-item spacing.
          isMobile && variant === 'knowledge' && 'touch-mobile:pt-2 touch-mobile:px-2 touch-mobile:pb-0',
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
            className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-[5px] outline-none data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40"
          >
            <Outlined.Attachment size={16} className="text-[#999]" />
            <span className="text-[14px] font-normal text-slate-700">{localize('com_ui_upload_files')}</span>
          </DropdownMenuItem>
        )}

        {/* Upload folder — only rendered when the caller supplies a handler, i.e.
            task mode. Daily chat has no agent workspace to rebuild a tree in. */}
        {variant === 'plus' && showFileUpload && onFolderUploadClick
          && ((!isMobile) || (isMobile && mobilePanel === 'root')) && (
          <DropdownMenuItem
            disabled={fileUploadDisabled}
            onSelect={(e) => {
              e.preventDefault();
              if (fileUploadDisabled) return;
              onFolderUploadClick();
            }}
            className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-[5px] outline-none data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40"
          >
            <Outlined.FolderClose size={16} className="text-[#999]" />
            <span className="text-[14px] font-normal text-slate-700">{localize('com_ui_upload_folder')}</span>
          </DropdownMenuItem>
        )}

        {/* Knowledge pill (mobile): show the SPACES list directly — no drill.
            Matches the desktop layout (title + list) so both surfaces feel the
            same; only the outer width / position adapt to the smaller screen. */}
        {variant === 'knowledge' && isMobile && (
          <div className="flex min-h-0 w-full flex-1 flex-col">
            <p className="mb-1 shrink-0 px-2 py-[5px] text-[14px] font-medium leading-[22px] text-[#1A1A1A]">
              {localize('com_ui_knowledge_space')}
            </p>
            <KnowledgeListPanel
              placeholder={localize('com_chat_knowledge_placeholder_search_space')}
              keyword={spaceKeyword}
              setKeyword={setSpaceKeyword}
              groups={spaceListGroups}
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
              groups={spaceListGroups}
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
                'mt-0.5 flex cursor-pointer items-center justify-between rounded-md px-2 py-[5px] outline-none',
              )}
            >
              <div className="flex items-center gap-2">
                <div className="relative">
                  {/* Icon turns brand-blue once an org KB is selected (no dot). */}
                  <Outlined.Books size={16} className={selectedOrgKbs.length > 0 ? "text-blue-500" : "text-[#999]"} />
                </div>
                <span className="text-[14px] font-normal text-slate-700">
                  {localize('com_tools_org_knowledge')}
                </span>
              </div>
            </DropdownMenuSubTrigger>

            <DropdownMenuSubContent
              alignOffset={orgLayout.alignOffset}
              collisionPadding={BOTTOM_GAP}
              className="ml-2 flex w-[240px] flex-col overflow-hidden rounded-lg border-slate-100 bg-white pt-2 px-2 pb-0 shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]"
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
            className="mt-0.5 flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-[5px] outline-none"
          >
            <div className="flex min-w-0 items-center gap-2">
              <div className="relative shrink-0">
                {/* Icon turns brand-blue once an org KB is selected (no dot). */}
                <Outlined.Books size={16} className={selectedOrgKbs.length > 0 ? "text-blue-500" : "text-[#999]"} />
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
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-[5px] outline-none"
            >
              <Outlined.ListSuccess size={16} className={taskModeActive ? 'text-blue-500' : 'text-[#999]'} />
              <span className={cn('flex-1 text-[14px] font-normal', taskModeActive ? 'text-blue-500' : 'text-slate-700')}>
                {localize('com_linsight_task_mode')}
              </span>
              {taskModeActive && <Outlined.Check size={14} className="text-blue-500" />}
            </DropdownMenuItem>
            {/* 添加 Skill — 桌面：悬停展开技能选择器；移动 root：下钻进技能面板。
                选中技能即进入任务模式（由 renderSkillSubmenu 内部导航），故传入
                close 让选择器先关掉「+」菜单，避免 popover 跳位。 */}
            {renderSkillSubmenu && (
              !isMobile ? (
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger
                    className={cn(
                      'flex cursor-pointer items-center justify-between rounded-md px-2 py-[5px] outline-none',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Outlined.Newspaper size={16} className={skillSelected ? 'text-blue-500' : 'text-[#999]'} />
                      <span className="text-[14px] font-normal text-slate-700">
                        {localize('com_linsight_add_skill')}
                      </span>
                    </div>
                  </DropdownMenuSubTrigger>
                  {/* Layout mirrors the knowledge panel shell (variant === 'knowledge' above). */}
                  <DropdownMenuSubContent className="ml-2 flex max-h-[256px] w-[240px] flex-col gap-0 overflow-hidden rounded-lg border-0 bg-white px-2 pb-0 pt-2 shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]">
                    {renderSkillSubmenu(() => setRootOpen(false))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              ) : (
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault();
                    setMobilePanel('skill');
                  }}
                  className="flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-[5px] outline-none"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <Outlined.Newspaper size={16} className={skillSelected ? 'text-blue-500' : 'text-[#999]'} />
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