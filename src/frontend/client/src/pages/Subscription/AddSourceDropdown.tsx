import { FileText, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { truncateName, type InformationSource, type SourceType } from "~/mock/sources";
import {
    ChannelBusinessType,
    listManagerSourcesApi,
    type ManagerSource,
    addWechatSourceApi
} from "~/api/channels";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";

const MAX_SOURCES = 50;
const MAX_NAME_DISPLAY = 20;

function looksLikeUrl(s: string): boolean {
    const t = s.trim();
    return /^https?:\/\//i.test(t) || /^[a-z0-9-]+\.(com|cn|org|net|gov)(\/[^\s]*)?$/i.test(t);
}

type ViewMode = "list" | "noResultNonUrl" | "noResultUrl" | "wechatProcessing";

function looksLikeWechatArticleUrl(s: string): boolean {
    return s.trim().toLowerCase().includes("mp.weixin.qq.com/");
}

interface AddSourceDropdownProps {
    sources: InformationSource[];
    onSourcesChange: (sources: InformationSource[]) => void;
    expanded: boolean;
    onExpandChange: (v: boolean) => void;
    onRequestCrawl: (url: string) => void;
}

export function AddSourceDropdown({
    sources,
    onSourcesChange,
    expanded,
    onExpandChange,
    onRequestCrawl
}: AddSourceDropdownProps) {
    const [activeTab, setActiveTab] = useState<SourceType>("official_account");
    const [searchKeyword, setSearchKeyword] = useState("");
    /** 展开时的待确认列表，只有点「确认添加」才提交 */
    const [pendingSources, setPendingSources] = useState<InformationSource[]>([]);
    const [wechatSources, setWechatSources] = useState<InformationSource[]>([]);
    const [websiteSources, setWebsiteSources] = useState<InformationSource[]>([]);
    const [loadingSources, setLoadingSources] = useState(false);
    const prevExpanded = useRef(false);
    const processingWechatRef = useRef("");
    const localize = useLocalize();

    useEffect(() => {
        if (expanded && !prevExpanded.current) setPendingSources([...sources]);
        prevExpanded.current = expanded;
    }, [expanded, sources]);

    const allSourcesByTab = activeTab === "official_account" ? wechatSources : websiteSources;
    const filteredSources = useMemo(() => {
        const kw = searchKeyword.trim().toLowerCase();
        if (!kw) return allSourcesByTab;
        const combined = [...wechatSources, ...websiteSources];
        return combined.filter(
            (s) =>
                s.name.toLowerCase().includes(kw) ||
                (s.url && s.url.toLowerCase().includes(kw))
        );
    }, [allSourcesByTab, searchKeyword, wechatSources, websiteSources]);

    const isSearchMode = searchKeyword.trim().length > 0;

    /** 展开时用待确认列表，用于列表内勾选状态与上限判断 */
    const workingSources = expanded ? pendingSources : sources;
    const selectedIds = new Set(workingSources.map((s) => s.id));
    const canSelectMore = workingSources.length < MAX_SOURCES;
    const isAtLimit = workingSources.length >= MAX_SOURCES;

    const viewMode: ViewMode = useMemo(() => {
        if (!searchKeyword.trim()) return "list";
        if (filteredSources.length > 0) return "list";
        if (looksLikeWechatArticleUrl(searchKeyword)) return "wechatProcessing";
        return looksLikeUrl(searchKeyword) ? "noResultUrl" : "noResultNonUrl";
    }, [searchKeyword, filteredSources.length]);

    // 加载信息源列表（真实接口）
    useEffect(() => {
        if (!expanded) return;
        const load = async (business_type: ChannelBusinessType) => {
            setLoadingSources(true);
            try {
                const res = await listManagerSourcesApi({ business_type, page: 1, page_size: 20 });
                const mapped: InformationSource[] = (res.data || []).map((s: ManagerSource) => ({
                    id: s.id,
                    name: s.name,
                    avatar: s.avatar,
                    url: s.url,
                    type: s.business_type === "wechat" ? "official_account" : "website"
                }));
                if (business_type === "wechat") setWechatSources(mapped);
                else setWebsiteSources(mapped);
            } catch {
                // 静默失败，保留当前列表
            } finally {
                setLoadingSources(false);
            }
        };
        // 当前 tab 对应的业务类型
        const currentType: ChannelBusinessType =
            activeTab === "official_account" ? "wechat" : "website";
        load(currentType);
    }, [expanded, activeTab]);

    useEffect(() => {
        if (!expanded) return;
        if (viewMode !== "wechatProcessing") {
            processingWechatRef.current = "";
            return;
        }
        const target = searchKeyword.trim();
        if (!target || processingWechatRef.current === target) return;
        processingWechatRef.current = target;

        const timer = setTimeout(() => {
            (async () => {
                try {
                    // 调用后端创建公众号信息源
                    const res = await addWechatSourceApi({ url: target });
                    const raw: any = (res as any)?.data ?? res ?? {};
                    const created: InformationSource = {
                        id: String(raw.id ?? raw.source_id ?? `wx-${Date.now()}`),
                        name: String(raw.name ?? raw.title ?? localize("wechat_source_name") ?? "公众号内容源"),
                        avatar: raw.avatar,
                        url: raw.url ?? target,
                        type: "official_account"
                    };
                    setWechatSources((prev) => {
                        // 避免重复
                        if (prev.some((s) => s.id === created.id)) return prev;
                        return [...prev, created];
                    });
                    setPendingSources((prev) => {
                        if (prev.length >= MAX_SOURCES) return prev;
                        if (prev.some((s) => s.id === created.id || s.url === created.url)) return prev;
                        return [...prev, created];
                    });
                } catch {
                    // 失败则退回为本地添加，保证交互不“卡死”
                    setPendingSources((prev) => {
                        if (prev.length >= MAX_SOURCES) return prev;
                        if (prev.some((s) => s.url === target)) return prev;
                        return [
                            ...prev,
                            {
                                id: `wx-${Date.now()}`,
                                name: localize("wechat_source_name") || "公众号内容源",
                                type: "official_account",
                                url: target
                            }
                        ];
                    });
                } finally {
                    setSearchKeyword("");
                    processingWechatRef.current = "";
                }
            })();
        }, 1800);

        return () => clearTimeout(timer);
    }, [expanded, viewMode, searchKeyword]);

    const toggleSource = (source: InformationSource) => {
        if (selectedIds.has(source.id)) {
            const next = workingSources.filter((s) => s.id !== source.id);
            if (expanded) setPendingSources(next);
            else onSourcesChange(next);
        } else if (canSelectMore) {
            const next = [...workingSources, source];
            if (expanded) setPendingSources(next);
            else onSourcesChange(next);
        }
    };

    const handleClearSearch = () => setSearchKeyword("");

    const handleConfirm = () => {
        onSourcesChange([...pendingSources]);
        onExpandChange(false);
        setSearchKeyword("");
    };

    const handleCancel = () => {
        onExpandChange(false);
        setSearchKeyword("");
    };

    const displayList = filteredSources;

    return (
        <div className="relative">
            {/* 没点击时：触发区+已选列表 同一灰色整体 */}
            {!expanded && (
                <div
                    className="rounded-lg border border-[#E5E6EB] bg-[#F7F8FA] overflow-hidden"
                    role="button"
                    tabIndex={0}
                    onClick={() => onExpandChange(true)}
                    onKeyDown={(e) => e.key === "Enter" && onExpandChange(true)}
                >
                    <div className="flex items-center gap-2 px-4 py-3">
                        <Plus className="size-4 flex-shrink-0 text-[#86909C]" />
                        <span className="flex-1 text-[14px] text-[#86909C] text-left">
                            可添加公众号和网页作为该频道的信息源
                        </span>
                        <span className="flex-shrink-0 text-[12px] text-[#86909C]">
                            {sources.length}/{MAX_SOURCES}
                        </span>
                    </div>
                    {sources.length > 0 && (
                        <div className="border-t border-[#E5E6EB] bg-white">
                            {[...sources].reverse().map((s) => (
                                <div
                                    key={s.id}
                                    className="flex items-center gap-3 py-2 px-4 hover:bg-[#FAFAFA]"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    <div className="w-8 h-8 rounded-full bg-[#E5E6EB] flex-shrink-0 overflow-hidden">
                                        {s.avatar ? (
                                            <img src={s.avatar} alt="" className="w-full h-full object-cover" />
                                        ) : (
                                            <div className="w-full h-full flex items-center justify-center text-[12px] text-[#86909C]">
                                                {s.name[0]}
                                            </div>
                                        )}
                                    </div>
                                    <span className="flex-1 text-[14px] text-[#1D2129] truncate">
                                        {truncateName(s.name)}
                                        <span
                                            className={cn(
                                                "text-[11px] px-0.5 rounded flex-shrink-0 ml-2",
                                                " border text-[#165DFF] border-[#165DFF]"  // 统一的白底蓝框蓝字
                                            )}
                                        >
                                            {s.type === "official_account" ? "公众号" : "网站"}
                                        </span>
                                    </span>
                                    <button
                                        type="button"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onSourcesChange(sources.filter((x) => x.id !== s.id));
                                        }}
                                        className="p-1 text-[#86909C] hover:text-[#F53F3F] rounded"
                                    >
                                        <Trash2 className="size-4" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* 展开时：占位保持布局 */}
            {expanded && (
                <div className="flex items-center gap-2 h-[46px]">
                    <div className="flex-1" />
                    <span className="flex-shrink-0 text-[12px] text-[#86909C]">
                        {pendingSources.length}/{MAX_SOURCES}
                    </span>
                </div>
            )}

            {/* 添加时：输入框+Tab+列表 同一整体，高 z-index 浮动，实时搜索 */}
            {expanded && (
                <div className="absolute left-0 right-0 top-0 z-[100] rounded-lg border border-[#E5E6EB] bg-white shadow-[0_4px_16px_rgba(0,0,0,0.12)] overflow-hidden min-w-[400px]">
                    <div className="flex items-center gap-2 pb-2">
                        <div className="relative flex-1 rounded-lg m-1">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#86909C]" />
                            <Input
                                value={searchKeyword}
                                onChange={(e) => setSearchKeyword(e.target.value)}
                                placeholder={localize("enter_official_account")}
                                className="pl-9 pr-9 h-10 text-[14px] border-none bg-white w-full  rounded-none"
                                autoFocus
                            />
                            {searchKeyword && (
                                <button
                                    type="button"
                                    onClick={handleClearSearch}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909C] hover:text-[#4E5969]"
                                >
                                    <X className="size-4" />
                                </button>
                            )}
                        </div>
                    </div>
                    {/* 仅非搜索时显示 Tab；搜索时混合展示，类型在名称后 */}
                    {!isSearchMode && (
                        <div className="flex gap-4 px-4 border-b border-[#E5E6EB]">
                            <button
                                type="button"
                                onClick={() => setActiveTab("official_account")}
                                className={cn(
                                    "pb-2 text-[14px] font-medium border-b-2 -mb-px",
                                    activeTab === "official_account"
                                        ? "text-[#165DFF] border-[#165DFF]"
                                        : "text-[#86909C] border-transparent"
                                )}
                            >
                                {localize("official_account")}
                            </button>
                            <button
                                type="button"
                                onClick={() => setActiveTab("website")}
                                className={cn(
                                    "pb-2 text-[14px] font-medium border-b-2 -mb-px",
                                    activeTab === "website"
                                        ? "text-[#165DFF] border-[#165DFF]"
                                        : "text-[#86909C] border-transparent"
                                )}
                            >
                                {localize("website")}
                            </button>
                        </div>
                    )}
                    <div
                        className={cn(
                            "overflow-y-auto hide-scrollbar",
                            viewMode === "list" ? "max-h-[420px]" : "h-[520px]"
                        )}
                    >
                        {viewMode === "noResultNonUrl" && (
                            <div className="h-[432px] flex flex-col items-center justify-center text-center">
                                <div className="mb-4 rounded-full border border-dashed border-[#165DFF] p-3">
                                    <FileText className="size-8 text-[#165DFF]" strokeWidth={1.6} />
                                </div>
                                <p className="text-[14px] leading-6 text-[#4E5969]">
                                    {localize("no_source_collected") ||
                                        "暂时没有收录该信源，试试在上方输入框中输入完整的网址，进行检索或添加"}
                                </p>
                            </div>
                        )}
                        {viewMode === "noResultUrl" && (
                            <div className="h-[432px] flex flex-col items-center justify-center text-center">
                                <div className="mb-4 rounded-full border border-dashed border-[#165DFF] p-3">
                                    <FileText className="size-8 text-[#165DFF]" strokeWidth={1.6} />
                                </div>
                                <p className="text-[14px] text-[#4E5969] mb-5">
                                    {localize("website_not_indexed") || "网站尚未入库，是否需要爬取"}
                                </p>
                                <div className="flex gap-3 justify-center">
                                    <Button
                                        variant="secondary"
                                        onClick={handleClearSearch}
                                        className="h-9 min-w-[74px] border border-[#E5E6EB] bg-white text-[#4E5969]"
                                    >
                                        {localize("do_not_crawl")}
                                    </Button>
                                    <Button
                                        onClick={() => {
                                            onRequestCrawl(searchKeyword.trim());
                                        }}
                                        className="h-9 min-w-[74px] bg-[#165DFF] hover:bg-[#4080FF]"
                                    >
                                        {localize("confirm_crawl") || "确认爬取"}
                                    </Button>
                                </div>
                            </div>
                        )}
                        {viewMode === "wechatProcessing" && (
                            <div className="h-[432px] flex flex-col items-center justify-center text-center">
                                <div className="mb-4 rounded-full border border-dashed border-[#165DFF] p-3">
                                    <FileText className="size-8 text-[#165DFF]" strokeWidth={1.6} />
                                </div>
                                <p className="text-[14px] text-[#4E5969] mb-5">
                                    {localize("detect_wechat_link") || "检测到是公众号链接，正在添加中..."}
                                </p>
                                <Button
                                    variant="secondary"
                                    onClick={handleClearSearch}
                                    className="h-9 min-w-[84px] border border-[#E5E6EB] bg-white text-[#4E5969]"
                                >
                                    {localize("do_not_add")}
                                </Button>
                            </div>
                        )}
                        {viewMode === "list" && (
                            <>
                                {displayList.length === 0 ? (
                                    <div className="p-8 text-center text-[14px] text-[#86909C]">暂无数据</div>
                                ) : (
                                    <div className="divide-y divide-[#E5E6EB]">
                                        {displayList.map((source) => {
                                            const sel = selectedIds.has(source.id);
                                            const dis = !sel && isAtLimit;
                                            return (
                                                <div
                                                    key={source.id}
                                                    onClick={() => !dis && toggleSource(source)}
                                                    className={cn(
                                                        "flex items-center gap-3 px-4 py-3 cursor-pointer",
                                                        dis && "opacity-60 cursor-not-allowed",
                                                        sel && "bg-[#E8F3FF]"
                                                    )}
                                                >
                                                    <div className="w-9 h-9 rounded-full bg-[#F2F3F5] overflow-hidden flex-shrink-0">
                                                        {source.avatar ? (
                                                            <img src={source.avatar} alt="" className="w-full h-full object-cover" />
                                                        ) : (
                                                            <div className="w-full h-full flex items-center justify-center text-[12px] text-[#86909C]">
                                                                {source.name[0]}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <span
                                                        className={cn(
                                                            "flex-1 text-[14px] text-[#1D2129] truncate",
                                                            source.type === "website" && source.url && "hover:underline cursor-pointer"
                                                        )}
                                                        onClick={
                                                            source.type === "website" && source.url
                                                                ? (e) => {
                                                                    e.stopPropagation();
                                                                    window.open(source.url, "_blank");
                                                                }
                                                                : undefined
                                                        }
                                                    >
                                                        {truncateName(source.name, MAX_NAME_DISPLAY)}
                                                        {isSearchMode && <span
                                                            className={cn(
                                                                "text-[12px] px-2 py-0.5 rounded flex-shrink-0",
                                                                source.type === "official_account"
                                                                    ? "bg-[#E8F3FF] text-[#165DFF]"
                                                                    : "bg-[#FFF7E8] text-[#F7BA2E]"
                                                            )}
                                                        >
                                                            {source.type === "official_account" ? "公众号" : "网站"}
                                                        </span>}
                                                    </span>

                                                    <div
                                                        className="flex-shrink-0"
                                                        onClick={(e) => e.stopPropagation()}
                                                    >
                                                        <Checkbox
                                                            checked={sel}
                                                            onCheckedChange={() => !dis && toggleSource(source)}
                                                            className="rounded border-[#C9CDD4] data-[state=checked]:bg-[#165DFF] data-[state=checked]:border-[#165DFF]"
                                                        />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                    {viewMode === "list" && (
                        <div className="flex justify-between items-center px-4 py-3 border-t border-[#E5E6EB] bg-[#FAFAFA]">
                            <span className="text-[12px] text-[#86909C]">
                                频道信息源总数: {pendingSources.length}/{MAX_SOURCES}
                            </span>
                            <div className="flex gap-2">
                                <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={handleCancel}
                                    className="bg-white border border-[#E5E6EB]"
                                >
                                    {localize("cancel")}
                                </Button>
                                <Button size="sm" onClick={handleConfirm} className="bg-[#165DFF]">
                                    {localize("confirm_add") || "确认添加"}
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            )}

        </div>
    );
}
