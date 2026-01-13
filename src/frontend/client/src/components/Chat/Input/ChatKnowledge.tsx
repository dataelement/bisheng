import { useEffect, useState, useMemo } from "react";
import {
  Check,
  BookOpen,
  BookOpenText,
  Loader2,
  SearchIcon,
} from "lucide-react";
import { Switch, Input } from "~/components/ui";
import { Select, SelectContent, SelectTrigger } from "~/components/ui/Select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { useGetOrgToolList, useModelBuilding } from "~/data-provider";
import { BsConfig } from "~/data-provider/data-provider/src";
import { cn } from "~/utils";
import { useToastContext } from "~/Providers";

// Custom Hook: Debounce value
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}
const PERSONAL_KB = {
  id: "personal_knowledge_base",
  name: "个人知识库",
};
export const ChatKnowledge = ({
  config,
  disabled,
  searchType,
  setSearchType,
  enableOrgKb,
  setEnableOrgKb,
  selectedOrgKbs,
  setSelectedOrgKbs,
}: {
  config?: BsConfig;
  disabled: boolean;
  searchType: string;
  setSearchType: React.Dispatch<React.SetStateAction<string>>;
  enableOrgKb: boolean;
  setEnableOrgKb: (v: boolean) => void;
  selectedOrgKbs: { id: string; name: string }[];
  setSelectedOrgKbs: React.Dispatch<
    React.SetStateAction<{ id: string; name: string }[]>
  >;
}) => {
  const [building] = useModelBuilding();
  const localize = useLocalize();
  const PAGE_SIZE = 20;
  const MAX_ORG_KB = 50;

  // Search and Pagination State
  const [keyword, setKeyword] = useState("");
  const debouncedKeyword = useDebounce(keyword, 500);
  const [page, setPage] = useState(1);
  const [allOrgKbs, setAllOrgKbs] = useState<any[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const { showToast } = useToastContext();

  // Fetch Data
  const { data: currentPageData, isFetching } = useGetOrgToolList({
    page,
    page_size: PAGE_SIZE,
    name: debouncedKeyword,
  });

  // Reset list when search keyword changes
  useEffect(() => {
    setPage(1);
    setAllOrgKbs([]);
    setHasMore(true);
  }, [debouncedKeyword]);

  // Accumulate data when page or response changes
  useEffect(() => {
    if (currentPageData) {
      setAllOrgKbs((prev) => {
        if (page === 1) return [...currentPageData];
        const newItems = currentPageData.filter(
          (item: any) => !prev.some((p) => p.id === item.id)
        );
        return [...prev, ...newItems];
      });
      setHasMore(currentPageData.length === PAGE_SIZE);
    }
  }, [currentPageData, page, debouncedKeyword]);

  // Infinite Scroll Handler
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
    if (
      scrollHeight - scrollTop <= clientHeight + 10 &&
      !isFetching &&
      hasMore
    ) {
      setPage((prev) => prev + 1);
    }
  };

  const toggleOrgKb = (kb: { id: string; name: string }) => {
    setSelectedOrgKbs((prev) => {
      const exists = prev.some((i) => i.id === kb.id);
      if (exists) return prev.filter((i) => i.id !== kb.id);
      if (prev.length >= MAX_ORG_KB) {
        showToast({
          message: localize("kbLimitReached"),
          status: "error",
        });
        return prev;
      }
      return [{ id: kb.id, name: kb.name }, ...prev];
    });
  };
  useEffect(() => {
    setSelectedOrgKbs((prev) => {
      const filtered = prev.filter((kb) => kb.id !== PERSONAL_KB.id);
      return searchType === "knowledgeSearch" ? [...filtered, PERSONAL_KB] : filtered;
    });
  }, [searchType]);

  useEffect(() => {
    if (!enableOrgKb) {
      // 仅删除组织 KB
      setSelectedOrgKbs((prev) =>
        prev.filter((kb) => kb.id === PERSONAL_KB.id || kb.id === PERSONAL_KB.id)
      );
    }
  }, [enableOrgKb, setSelectedOrgKbs]);

  useEffect(() => {
    if (!selectedOrgKbs.length && !enableOrgKb) {
      setSelectedOrgKbs([]);
      setEnableOrgKb(false);
    }
  }, []);

  return (
    <Select disabled={disabled}>
      <SelectTrigger
        className={cn(
          "h-7 rounded-full px-2 data-[state=open]:border-blue-500",
          (searchType === "knowledgeSearch" || enableOrgKb) && "bg-blue-100"
        )}
      >
        <div
          className={cn(
            "flex gap-2 items-center ",
            (searchType === "knowledgeSearch" || enableOrgKb) && "text-blue-600"
          )}
        >
          <BookOpenText size={16} />
          <span className="text-xs">
            {localize("com_tools_knowledge_base")}
          </span>
        </div>
      </SelectTrigger>

      <SelectContent className="bg-white rounded-xl p-3 w-64 shadow-lg border">
        {/* Section 1: Personal Knowledge Base */}

        <div className="flex justify-between items-center">
          <div className="flex gap-2 items-center">
            <BookOpen
              size={16}
              color="#595959"
              strokeWidth={2.75}
              className="text-slate-500"
            />
            <span className="text-xs font-medium">
              {localize("com_tools_personal_knowledge")}
            </span>
          </div>
          <Tooltip delayDuration={200}>
            <TooltipTrigger asChild>
              <div>
                <Switch
                  className="data-[state=checked]:bg-blue-600"
                  disabled={building || disabled}
                  checked={searchType === "knowledgeSearch"}
                  onCheckedChange={(val) =>
                    setSearchType(val ? "knowledgeSearch" : "")
                  }
                />
              </div>
            </TooltipTrigger>
            {building && (
              <TooltipContent>
                {localize("com_tools_knowledge_rebuilding")}
              </TooltipContent>
            )}
          </Tooltip>
        </div>

        {/* Section 2: Organization Knowledge Base */}
        <div className="flex justify-between items-center mt-3  -ml-0.5">
          <div className="flex gap-2 items-center">
            <img
              className="size-5 text-slate-500"
              src={__APP_ENV__.BASE_URL + "/assets/books.svg"}
              alt=""
            />
            <span className="text-xs font-medium">
              {localize("com_tools_org_knowledge")}
            </span>
          </div>
          <Switch
            checked={enableOrgKb}
            onCheckedChange={setEnableOrgKb}
            disabled={disabled}
            className="data-[state=checked]:bg-blue-600"
          />
        </div>

        {/* Org KB Search and List */}
        {enableOrgKb && (
          <div className="mt-3">
            <div className="relative">
              <Input
                className="h-8 text-xs mb-2 bg-slate-50 border-none focus-visible:ring-1 focus-visible:ring-blue-500 pr-8" // 新增 pr-8 给图标留空间
                placeholder={localize("com_tools_knowledge_base_search")}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
              {/* 搜索图标 - 固定在输入框右侧 */}
              <SearchIcon
                className="absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400"
                aria-hidden="true"
              />
            </div>

            <div
              className="max-h-52 overflow-y-auto custom-scrollbar"
              onScroll={handleScroll}
            >
              {allOrgKbs.map((item) => {
                const checked = selectedOrgKbs.some((kb) => kb.id === item.id);
                return (
                  <div
                    key={item.id}
                    onClick={() => toggleOrgKb(item)}
                    className="flex justify-between items-center px-2 py-2 rounded-md cursor-pointer text-xs hover:bg-slate-50 group"
                  >
                    <span className="truncate flex-1 pr-2 text-slate-700">
                      {item.name}
                    </span>
                    {checked && (
                      <Check size={14} className="text-blue-600 shrink-0" />
                    )}
                  </div>
                );
              })}

              {/* Loading & Empty State Feedback */}
              {isFetching && (
                <div className="flex justify-center py-2">
                  <Loader2 size={14} className="animate-spin text-slate-400" />
                </div>
              )}

              {/* {allOrgKbs.length === 0 && (
                <div className="text-center text-[10px] text-slate-400 py-2 border-t mt-1">
                  {localize("com_tools_no_more")}
                </div>
              )} */}

              {!isFetching && allOrgKbs.length === 0 && (
                <div className="text-center text-xs text-slate-400 py-6">
                  {localize("com_tools_no_results")}
                </div>
              )}
            </div>
          </div>
        )}
      </SelectContent>
    </Select>
  );
};
