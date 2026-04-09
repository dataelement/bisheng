import {
  BookOpenText,
  Check,
  ChevronRight,
  Loader2,
  SearchIcon,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  getManagedSpacesApi,
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
import BookOpen from "~/components/ui/icon/BookOpen";
import BooksIcon from "~/components/ui/icon/Books";
import { useGetOrgToolList } from "~/hooks/queries/data-provider";
import { BsConfig } from "~/types/chat";
import { useLocalize } from "~/hooks";
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

const MAX_SUB_HEIGHT = 320;
const BOTTOM_GAP = 8;

function useSubMenuLayout(menuRef: React.RefObject<HTMLDivElement | null>, triggerKey: string, open: boolean) {
  const [alignOffset, setAlignOffset] = useState(0);
  const [maxH, setMaxH] = useState<number>(MAX_SUB_HEIGHT);

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

      const available = window.innerHeight - menuRect.top - BOTTOM_GAP;
      setMaxH(Math.min(Math.max(available, 0), MAX_SUB_HEIGHT));
    };

    requestAnimationFrame(update);
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
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
          className="h-[28px] text-xs bg-white border border-[#ECECEC] rounded-[6px] pl-8 focus-visible:ring-1 focus-visible:ring-blue-500/20"
          placeholder={placeholder}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onClick={(e) => e.stopPropagation()}
        />
      </div>

      {/* 滚动列表 */}
      <div
        className="overflow-y-auto flex flex-col gap-0.5 scrollbar-on-hover min-h-0 flex-1"
        onScroll={handleScroll}
      >
        {items.map((item) => {
          // 判断是否选中
          const isChecked = selectedItems.some((s) => s.id === item.id);
          return (
            <DropdownMenuItem
              key={item.id}
              onSelect={(e) => {
                e.preventDefault();
                onToggle(item);
              }}
              className="flex items-center gap-2.5 px-0.5 py-2 cursor-pointer rounded-lg hover:bg-slate-50 focus:bg-slate-50 outline-none"
            >
              <div
                className={cn(
                  "size-4 rounded border flex items-center justify-center transition-colors shrink-0",
                  isChecked ? "bg-blue-600 border-blue-600" : "border-slate-300 bg-white"
                )}
              >
                {isChecked && <Check size={12} className="text-white stroke-[3]" />}
              </div>
              <span className="truncate flex-1 text-[13px] text-slate-700 leading-none">
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
  config,
  disabled,
  value = [],
  onChange,
}: {
  config?: BsConfig;
  disabled: boolean;
  value: KnowledgeItem[];
  onChange: (val: KnowledgeItem[]) => void;
}) => {
  console.log('value :>> ', value);
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
      const spaces = await getManagedSpacesApi({ order_by: 'update_time' });
      setAllSpaces(spaces);
    } catch (err) {
      console.error("[ChatKnowledge] Failed to load spaces:", err);
    } finally {
      setSpaceFetching(false);
    }
  }, []);

  useEffect(() => {
    loadSpaces();
  }, [loadSpaces]);

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

  // Org KB data fetching (paginated via react-query)
  const { data: orgData, isFetching: orgFetching } = useGetOrgToolList({
    page: orgPage, page_size: PAGE_SIZE, name: debouncedOrgKeyword, sort_by: 'name',
  });

  useEffect(() => {
    setOrgPage(1);
    setAllOrgKbs([]);
  }, [debouncedOrgKeyword]);

  useEffect(() => {
    if (orgData) {
      setAllOrgKbs((prev) => (orgPage === 1 ? [...orgData] : [...prev, ...orgData]));
      setHasMoreOrg(orgData.length === PAGE_SIZE);
    }
  }, [orgData, orgPage]);

  // checked data
  const handleToggle = (item: any, type: KnowledgeType) => {
    const exists = value.some((i) => i.id === item.id && i.type === type);

    if (exists) {
      const nextValue = value.filter((i) => !(i.id === item.id && i.type === type));
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

      // 添加时注入 type
      const newItem: KnowledgeItem = { id: item.id, name: item.name, type };
      onChange([newItem, ...value]);
    }
  };

  const hasAnySelection = value.length > 0;

  const [openSub, setOpenSub] = useState<'space' | 'org' | null>(null);
  const menuContentRef = useRef<HTMLDivElement>(null);
  const spaceLayout = useSubMenuLayout(menuContentRef, 'space', openSub === 'space');
  const orgLayout = useSubMenuLayout(menuContentRef, 'org', openSub === 'org');

  return (
    <DropdownMenu>
      <DropdownMenuTrigger disabled={disabled}>
        <div className={cn(
          "flex bg-white items-center gap-2 h-7 px-3 rounded-full border border-slate-200 text-gray-500 cursor-pointer hover:border-blue-400 transition-all outline-none disabled:opacity-0",
          hasAnySelection && "!bg-[rgba(20,59,255,0.10)] !border-[#0253E8] text-[#0253E8] shadow-[0_1px_2px_0_rgba(0,0,0,0.05)]",
          disabled && "opacity-50 hover:border-slate-200 cursor-not-allowed"
        )}>
          <BookOpenText size={16} />
          <span className="text-xs break-keep">{localize('com_tools_knowledge_base')}</span>
          <ChevronRight size={14} className={cn("rotate-90", hasAnySelection ? "opacity-100" : "opacity-40")} />
        </div>
      </DropdownMenuTrigger>

      <DropdownMenuContent ref={menuContentRef} align="start" className="w-[200px] p-1.5 rounded-2xl shadow-xl border-slate-100">

        {/* 知识空间 */}
        <DropdownMenuSub open={openSub === 'space'} onOpenChange={() => {}}>
          <DropdownMenuSubTrigger
            data-sub-key="space"
            className={cn(
              "flex items-center justify-between rounded-xl outline-none cursor-pointer",
              "!bg-transparent hover:!bg-transparent focus:!bg-transparent"
            )}
            onPointerEnter={() => setOpenSub('space')}
          >
            <div className="flex items-center gap-3">
              <div className="relative">
                <BookOpen className="size-[18px] text-slate-600" />
                {selectedKnowledgeSpaces.length > 0 && (
                  <span className="absolute -top-1 -right-1 size-2.5 bg-blue-500 rounded-full border-2 border-white" />
                )}
              </div>
              <span className="text-[14px] text-slate-700 font-normal">{localize('com_ui_knowledge_space')}</span>
            </div>
          </DropdownMenuSubTrigger>

          <DropdownMenuSubContent
            alignOffset={spaceLayout.alignOffset}
            className="w-[280px] p-3 rounded-2xl shadow-2xl ml-2 border-slate-100 bg-white flex flex-col overflow-hidden"
            style={{
              '--tw-enter-duration': '0.35s',
              '--tw-enter-easing': 'ease-in-out',
              height: spaceLayout.maxH,
              maxHeight: MAX_SUB_HEIGHT,
            } as React.CSSProperties}
          >
            <p className="text-sm leading-5 py-1.5 mb-1 font-medium shrink-0">{localize('com_ui_knowledge_space')}</p>
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
          </DropdownMenuSubContent>
        </DropdownMenuSub>

        {/* 组织知识库 */}
        <DropdownMenuSub open={openSub === 'org'} onOpenChange={() => {}}>
          <DropdownMenuSubTrigger
            data-sub-key="org"
            className={cn(
              "flex items-center justify-between rounded-xl outline-none cursor-pointer mt-0.5",
              "!bg-transparent hover:!bg-transparent focus:!bg-transparent"
            )}
            onPointerEnter={() => setOpenSub('org')}
          >
            <div className="flex items-center gap-3">
              <div className="relative">
                <BooksIcon className="size-[18px] opacity-70" />
                {selectedOrgKbs.length > 0 && (
                  <span className="absolute -top-1 -right-1 size-2.5 bg-blue-500 rounded-full border-2 border-white" />
                )}
              </div>
              <span className="text-[14px] text-slate-700 font-normal">{localize('com_tools_org_knowledge')}</span>
            </div>
          </DropdownMenuSubTrigger>

          <DropdownMenuSubContent
            alignOffset={orgLayout.alignOffset}
            className="w-[280px] p-3 rounded-2xl shadow-2xl ml-2 border-slate-100 bg-white flex flex-col overflow-hidden"
            style={{
              '--tw-enter-duration': '0.35s',
              '--tw-enter-easing': 'ease-in-out',
              height: orgLayout.maxH,
              maxHeight: MAX_SUB_HEIGHT,
            } as React.CSSProperties}
          >
            <p className="text-sm leading-5 py-1.5 mb-1 font-medium shrink-0">{localize('com_tools_org_knowledge')}</p>
            <KnowledgeListPanel
              placeholder={localize('com_tools_knowledge_base_search')}
              keyword={orgKeyword}
              setKeyword={setOrgKeyword}
              items={allOrgKbs}
              selectedItems={selectedOrgKbs}
              onToggle={(item) => handleToggle(item, 'org')}
              isFetching={orgFetching}
              hasMore={hasMoreOrg}
              onLoadMore={() => setOrgPage(p => p + 1)}
              emptyText={localize('com_chat_knowledge_empty_no_org_kbs')}
            />
          </DropdownMenuSubContent>
        </DropdownMenuSub>

      </DropdownMenuContent>
    </DropdownMenu>
  );
};