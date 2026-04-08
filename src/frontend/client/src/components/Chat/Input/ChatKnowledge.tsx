import {
  BookOpen,
  BookOpenText,
  Check,
  ChevronRight,
  Loader2,
  SearchIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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
import { useGetOrgToolList } from "~/data-provider";
import { BsConfig } from "~/data-provider/data-provider/src";
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
    <div className="flex flex-col gap-3">
      {/* 搜索框 */}
      <div className="relative px-1">
        <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
        <Input
          className="h-8 text-xs bg-slate-50 border-none pl-8 focus-visible:ring-1 focus-visible:ring-blue-500/20"
          placeholder={placeholder}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onClick={(e) => e.stopPropagation()}
        />
      </div>

      {/* 滚动列表 */}
      <div
        className="max-h-[300px] overflow-y-auto custom-scrollbar flex flex-col gap-0.5"
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
              className="flex items-center gap-2.5 px-2.5 py-2 cursor-pointer rounded-lg hover:bg-slate-50 focus:bg-slate-50 outline-none"
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

  const [spaceKeyword, setSpaceKeyword] = useState("");
  const debouncedSpaceKeyword = useDebounce(spaceKeyword, 500);
  const [spacePage, setSpacePage] = useState(1);
  const [allSpaces, setAllSpaces] = useState<any[]>([]);
  const [hasMoreSpace, setHasMoreSpace] = useState(true);

  const { data: orgData, isFetching: orgFetching } = useGetOrgToolList({
    page: orgPage, page_size: PAGE_SIZE, name: debouncedOrgKeyword,
  });

  const { data: spaceData, isFetching: spaceFetching } = useGetOrgToolList({
    page: spacePage, page_size: PAGE_SIZE, name: debouncedSpaceKeyword,
  });

  useEffect(() => {
    setOrgPage(1);
    setAllOrgKbs([]);
  }, [debouncedOrgKeyword]);

  useEffect(() => {
    setSpacePage(1);
    setAllSpaces([]);
  }, [debouncedSpaceKeyword]);

  useEffect(() => {
    if (orgData) {
      setAllOrgKbs((prev) => (orgPage === 1 ? [...orgData] : [...prev, ...orgData]));
      setHasMoreOrg(orgData.length === PAGE_SIZE);
    }
  }, [orgData, orgPage]);

  useEffect(() => {
    if (spaceData) {
      setAllSpaces((prev) => (spacePage === 1 ? [...spaceData] : [...prev, ...spaceData]));
      setHasMoreSpace(spaceData.length === PAGE_SIZE);
    }
  }, [spaceData, spacePage]);

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
          message: type === 'space' ? "知识空间数量已达上限" : "组织知识库数量已达上限",
          status: "error"
        });
        return;
      }

      // 添加时注入 type
      const newItem: KnowledgeItem = { id: item.id, name: item.name, type };
      onChange([newItem, ...value]);
    }
  };

  const hasAnySelection = value.length > 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger disabled={disabled}>
        <div className={cn(
          "flex bg-white items-center gap-2 h-7 px-3 rounded-full border border-slate-200 text-gray-500 cursor-pointer hover:border-blue-400 transition-all outline-none disabled:opacity-0",
          hasAnySelection && "bg-blue-50 border-blue-200 text-blue-600",
          disabled && "opacity-50 hover:border-slate-200 cursor-not-allowed"
        )}>
          <BookOpenText size={16} />
          <span className="text-xs break-keep">知识库</span>
          <ChevronRight size={14} className="rotate-90 opacity-40" />
        </div>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-[200px] p-1.5 rounded-2xl shadow-xl border-slate-100">

        {/* 知识空间 */}
        <DropdownMenuSub>
          <DropdownMenuSubTrigger className="flex items-center justify-between rounded-xl hover:bg-slate-50 focus:bg-slate-50 outline-none cursor-pointer">
            <div className="flex items-center gap-3">
              <div className="relative">
                <BookOpen className="size-[18px] text-slate-600" />
                {selectedKnowledgeSpaces.length > 0 && (
                  <span className="absolute -top-1 -right-1 size-2.5 bg-blue-500 rounded-full border-2 border-white" />
                )}
              </div>
              <span className="text-[14px] text-slate-700 font-normal">知识空间</span>
            </div>
          </DropdownMenuSubTrigger>

          <DropdownMenuSubContent className="w-[280px] p-3 rounded-2xl shadow-2xl ml-2 border-slate-100 bg-white">
            <KnowledgeListPanel
              placeholder="搜索知识空间名称"
              keyword={spaceKeyword}
              setKeyword={setSpaceKeyword}
              items={allSpaces}
              selectedItems={selectedKnowledgeSpaces}
              onToggle={(item) => handleToggle(item, 'space')}
              isFetching={spaceFetching}
              hasMore={hasMoreSpace}
              onLoadMore={() => setSpacePage(p => p + 1)}
              emptyText="暂无知识空间"
            />
          </DropdownMenuSubContent>
        </DropdownMenuSub>

        {/* 组织知识库 */}
        <DropdownMenuSub>
          <DropdownMenuSubTrigger className="flex items-center justify-between rounded-xl hover:bg-slate-50 focus:bg-slate-50 outline-none cursor-pointer mt-0.5">
            <div className="flex items-center gap-3">
              <div className="relative">
                <img src={`${__APP_ENV__.BASE_URL}/assets/books.svg`} className="size-[18px] opacity-70" alt="" />
                {selectedOrgKbs.length > 0 && (
                  <span className="absolute -top-1 -right-1 size-2.5 bg-blue-500 rounded-full border-2 border-white" />
                )}
              </div>
              <span className="text-[14px] text-slate-700 font-normal">组织知识库</span>
            </div>
          </DropdownMenuSubTrigger>

          <DropdownMenuSubContent className="w-[280px] p-3 rounded-2xl shadow-2xl ml-2 border-slate-100 bg-white">
            <KnowledgeListPanel
              placeholder="搜索知识库名称"
              keyword={orgKeyword}
              setKeyword={setOrgKeyword}
              items={allOrgKbs}
              selectedItems={selectedOrgKbs}
              onToggle={(item) => handleToggle(item, 'org')}
              isFetching={orgFetching}
              hasMore={hasMoreOrg}
              onLoadMore={() => setOrgPage(p => p + 1)}
              emptyText="暂无组织知识库"
            />
          </DropdownMenuSubContent>
        </DropdownMenuSub>

      </DropdownMenuContent>
    </DropdownMenu>
  );
};