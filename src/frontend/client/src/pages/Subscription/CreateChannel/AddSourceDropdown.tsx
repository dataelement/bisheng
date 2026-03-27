import { Minus, Plus, Search, X, XCircle } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { NotificationSeverity } from "~/common";
import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { truncateName, type InformationSource } from "~/api/channels";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";
import { useSourceManager } from "../hooks/useSourceManager";
import { useConfirm, useToastContext } from "~/Providers";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle
} from "~/components/ui/AlertDialog";

const MAX_SOURCES = 50;
const MAX_NAME_DISPLAY = 20;
const EXTERNAL_LINK_ICON_SRC = `${__APP_ENV__.BASE_URL}/assets/channel/right-small-up.svg`;

interface AddSourceDropdownProps {
    sources: InformationSource[];
    onSourcesChange: (sources: InformationSource[]) => void;
    expanded: boolean;
    onExpandChange: (v: boolean) => void;
    onRequestCrawl: (url: string) => void;
    resetToken?: number;
}

export function AddSourceDropdown({
    sources,
    onSourcesChange,
    expanded,
    onExpandChange,
    onRequestCrawl,
    resetToken
}: AddSourceDropdownProps) {
    const localize = useLocalize();
    const mgr = useSourceManager(sources, onSourcesChange, expanded, onExpandChange);
    const confirm = useConfirm();
    const { showToast } = useToastContext();
    const [inputValue, setInputValue] = useState("");
    const [isCollapsedListScrolling, setIsCollapsedListScrolling] = useState(false);
    const collapsedListScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [isExpandedListScrolling, setIsExpandedListScrolling] = useState(false);
    const expandedListScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // 同步输入框展示值与已提交的搜索关键字（清空时）
    useEffect(() => {
        if (!mgr.searchKeyword) {
            setInputValue("");
        }
    }, [mgr.searchKeyword]);

    // 外部触发重置：清空输入框 + 清空已提交搜索关键字
    useEffect(() => {
        if (resetToken === undefined) return;
        setInputValue("");
        mgr.handleClearSearch();
    }, [resetToken]);

    const displayList = mgr.filteredSources;
    const handleCollapsedListScroll = () => {
        setIsCollapsedListScrolling(true);
        if (collapsedListScrollTimerRef.current) {
            clearTimeout(collapsedListScrollTimerRef.current);
        }
        collapsedListScrollTimerRef.current = setTimeout(() => {
            setIsCollapsedListScrolling(false);
        }, 500);
    };
    const handleExpandedListScroll = (e: any) => {
        setIsExpandedListScrolling(true);
        if (expandedListScrollTimerRef.current) {
            clearTimeout(expandedListScrollTimerRef.current);
        }
        expandedListScrollTimerRef.current = setTimeout(() => {
            setIsExpandedListScrolling(false);
        }, 500);

        if (mgr.viewMode !== "list") return;
        const el = e.currentTarget;
        const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
        if (nearBottom) {
            mgr.loadMoreSources();
        }
    };
    return (
        <div className="relative">
            {/* 没点击时：触发区+已选列表 同一灰色整体 */}
            {!expanded && (
                <div
                    className="rounded-lg border border-[#E5E6EB] bg-[#F7F8FA] overflow-hidden max-h-[480px] flex flex-col"
                    role="button"
                    tabIndex={0}
                    onClick={() => onExpandChange(true)}
                    onKeyDown={(e) => e.key === "Enter" && onExpandChange(true)}
                >
                    <div className="flex items-center gap-2 px-4 py-3 flex-shrink-0">
                        <Plus className="size-4 flex-shrink-0 text-[#86909C]" />
                        <span className="flex-1 text-[14px] text-[#86909C] text-left">{localize("com_subscription.add_official_accounts_and_webpages")}</span>
                        <span className="flex-shrink-0 text-[12px] text-[#86909C]">
                            {sources.length}/{MAX_SOURCES}
                        </span>
                    </div>
                    {sources.length > 0 && (
                        <div
                            className="border-t border-[#E5E6EB] bg-[#F7F8FA] overflow-y-auto scroll-on-scroll"
                            onScroll={handleCollapsedListScroll}
                            data-scrolling={isCollapsedListScrolling ? "true" : "false"}
                        >
                            {[...sources].reverse().map((s, idx, arr) => (
                                <div
                                    key={s.id}
                                    className={cn(
                                        "flex items-center gap-3 py-2 px-4 hover:bg-[#EEEFF1]",
                                        idx < arr.length - 1 && "border-b border-dashed border-[#D9D9D9]"
                                    )}
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
                                        <span
                                            className={cn(
                                                "inline-flex items-center max-w-full align-middle",
                                                s.type === "website" && s.url && "group/link text-[#1D2129] hover:text-[#165DFF] transition-colors"
                                            )}
                                            onClick={
                                                s.type === "website" && s.url
                                                    ? (e) => {
                                                        e.stopPropagation();
                                                        window.open(s.url, "_blank");
                                                    }
                                                    : undefined
                                            }
                                        >
                                            <span
                                                className={cn(
                                                    "truncate",
                                                    s.type === "website" && s.url && "hover:underline"
                                                )}
                                            >
                                                {truncateName(s.name)}
                                            </span>
                                            {s.type === "website" && s.url && (
                                                <img
                                                    src={EXTERNAL_LINK_ICON_SRC}
                                                    alt=""
                                                    className="ml-0.5 w-4 h-4 opacity-0 group-hover/link:opacity-100 transition-opacity flex-shrink-0"
                                                />
                                            )}
                                        </span>
                                        <span
                                            className={cn(
                                                "text-[11px] px-0.5 rounded flex-shrink-0 ml-4",
                                                s.type !== "official_account" && "-ml-0",
                                                " border text-[#165DFF] border-[#165DFF]"  // 统一的白底蓝框蓝字
                                            )}
                                        >
                                            {s.type === "official_account" ? localize("com_subscription.official_account") : localize("com_subscription.website")}
                                        </span>
                                    </span>
                                    <button
                                        type="button"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onSourcesChange(sources.filter((x) => x.id !== s.id));
                                        }}
                                        className="p-1 rounded"
                                        aria-label={localize("com_subscription.remove_source")}
                                    >
                                        <span className="inline-flex items-center justify-center w-3 h-3 border-[1px] border-[#F53F3F]">
                                            <Minus className="size-3 text-[#F53F3F]" />
                                        </span>
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
                        {mgr.pendingSources.length}/{MAX_SOURCES}
                    </span>
                </div>
            )}

            {/* 添加时：输入框+Tab+列表 同一整体，高 z-index 浮动，实时搜索 */}
            {expanded && (
                <div className="absolute left-0 right-0 top-0 z-[100] rounded-lg border border-[#E5E6EB] bg-white shadow-[0_4px_16px_rgba(0,0,0,0.12)] overflow-hidden min-w-[400px]">
                    <div className="flex items-center gap-2 pb-0 mb-2 border-b border-[#E5E6EB]">
                        <div className="relative flex-1 rounded-lg m-1">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#999999]" />
                            <Input
                                value={inputValue}
                                onChange={(e) => setInputValue(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter") {
                                        mgr.setSearchKeyword(inputValue.trim());
                                    }
                                }}
                                placeholder={localize("com_subscription.enter_official_account")}
                                className="pl-9 pr-9 h-10 text-[14px] border-none bg-white w-full  rounded-none"
                                autoFocus
                            />
                            {inputValue && (
                                <button
                                    type="button"
                                    onClick={() => {
                                        setInputValue("");
                                        mgr.handleClearSearch();
                                    }}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[#999999] hover:text-[#4E5969]"
                                >
                                    <X className="size-4" />
                                </button>
                            )}
                        </div>
                    </div>
                    {/* 仅非搜索时显示 Tab；搜索时混合展示，类型在名称后 */}
                    {!mgr.isSearchMode && (
                        <div className="flex gap-4 px-4 border-b border-[#E5E6EB]">
                            <button
                                type="button"
                                onClick={() => mgr.setActiveTab("official_account")}
                                className={cn(
                                    "pb-2 text-[14px] font-medium border-b-2 -mb-px",
                                    mgr.activeTab === "official_account"
                                        ? "text-[#165DFF] border-[#165DFF]"
                                        : "text-[#86909C] border-transparent"
                                )}
                            >
                                {localize("com_subscription.official_account")}
                            </button>
                            <button
                                type="button"
                                onClick={() => mgr.setActiveTab("website")}
                                className={cn(
                                    "pb-2 text-[14px] font-medium border-b-2 -mb-px",
                                    mgr.activeTab === "website"
                                        ? "text-[#165DFF] border-[#165DFF]"
                                        : "text-[#86909C] border-transparent"
                                )}
                            >
                                {localize("com_subscription.website")}
                            </button>
                        </div>
                    )}
                    <div
                        className={cn(
                            "overflow-y-auto scroll-on-scroll",
                            mgr.viewMode === "list" ? "max-h-[420px]" : "h-[520px]"
                        )}
                        onScroll={handleExpandedListScroll}
                        data-scrolling={isExpandedListScrolling ? "true" : "false"}
                    >
                        {mgr.viewMode === "noResultNonUrl" && (
                            <div className="h-[432px] flex flex-col items-center justify-center text-center">
                                <div className="mb-4 rounded-full p-3">
                                    <img
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/book.svg`}
                                        alt=""
                                        className="w-[120px] h-[120px] mb-5"
                                    />
                                </div>
                                <p className="text-[14px] leading-6 text-[#4E5969] whitespace-pre-line">
                                    {localize("com_subscription.no_source_collected") ||
                                        localize("com_subscription.source_not_indexed_try_full_url")}
                                </p>
                            </div>
                        )}
                        {mgr.viewMode === "noResultUrl" && (
                            <div className="h-[432px] flex flex-col items-center justify-center text-center">
                                <div className="mb-4">
                                    <img
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                        alt=""
                                        className="w-[120px] h-[120px]"
                                    />
                                </div>
                                <p className="text-[14px] text-[#4E5969] mb-5">
                                    {localize("com_subscription.website_not_indexed") || localize("com_subscription.website_not_in_database_crawl")}
                                </p>
                                <div className="flex gap-3 justify-center">
                                    <Button
                                        variant="secondary"
                                        onClick={mgr.handleClearSearch}
                                        className="h-8 rounded-[6px] min-w-[74px] inline-flex items-center justify-center leading-none border border-[#E5E6EB] bg-white text-[#4E5969]"
                                    >
                                        {localize("com_subscription.do_not_crawl")}
                                    </Button>
                                    <Button
                                        onClick={() => {
                                            // 前置校验：避免已满 50 个信源后仍打开爬取预览弹窗
                                            if (mgr.pendingSources.length >= MAX_SOURCES) {
                                                showToast({
                                                    message: "已达频道 50 个信源上限，无法再爬取",
                                                    severity: NotificationSeverity.WARNING,
                                                });
                                                return;
                                            }
                                            onRequestCrawl(mgr.searchKeyword.trim());
                                        }}
                                        className="h-8 rounded-[6px] min-w-[74px] inline-flex items-center justify-center leading-none bg-[#165DFF] hover:bg-[#4080FF]"
                                    >
                                        {localize("com_subscription.confirm_crawl")}
                                    </Button>
                                </div>
                            </div>
                        )}
                        {mgr.viewMode === "wechatProcessing" && (
                            <div className="h-[432px] flex flex-col items-center justify-center text-center">
                                <div className="mb-4">
                                    <img
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/loading.svg`}
                                        alt=""
                                        className="w-[120px] h-[120px]"
                                    />
                                </div>
                                <p className="text-[14px] text-[#4E5969] mb-5">
                                    {localize("com_subscription.detect_wechat_link") || localize("com_subscription.official_account_link_detected_adding")}
                                </p>
                                <Button
                                    variant="secondary"
                                    onClick={mgr.handleClearSearch}
                                    className="h-8 rounded-[6px] min-w-[84px] inline-flex items-center justify-center leading-none border border-[#E5E6EB] bg-white text-[#4E5969]"
                                >
                                    {localize("com_subscription.do_not_add")}
                                </Button>
                            </div>
                        )}
                        {mgr.viewMode === "list" && (
                            <>
                                {displayList.length === 0 ? (
                                    <div className="p-8 text-center text-[14px] text-[#86909C]">{localize("com_subscription.no_data")}</div>
                                ) : (
                                    <div className="">
                                        {displayList.map((source) => {
                                            const sel = mgr.selectedIds.has(source.id);
                                            const dis = !sel && mgr.isAtLimit;
                                            return (
                                                <div
                                                    key={source.id}
                                                    onClick={() => !dis && mgr.toggleSource(source)}
                                                    className={cn(
                                                        "flex items-center gap-3 px-4 py-3 cursor-pointer",
                                                        dis && "opacity-60 cursor-not-allowed",
                                                        sel && "bg-[#E8F3FF]"
                                                    )}
                                                >
                                                    <div className="w-6 h-6 rounded-full bg-[#F2F3F5] overflow-hidden flex-shrink-0">
                                                        {source.avatar ? (
                                                            <img src={source.avatar} alt="" className="w-full h-full object-cover" />
                                                        ) : (
                                                            <div className="w-full h-full flex items-center justify-center text-[12px] text-[#86909C]">
                                                                {source.name[0]}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <span className="flex-1 text-[14px] text-[#1D2129] truncate">
                                                        <span
                                                            className={cn(
                                                                "inline-flex items-center max-w-full align-middle",
                                                                source.type === "website" && source.url && "group/link cursor-pointer text-[#1D2129] hover:text-[#165DFF] transition-colors"
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
                                                            <span
                                                                className={cn(
                                                                    "truncate inline-block max-w-full",
                                                                    source.type === "website" && source.url && "hover:underline"
                                                                )}
                                                            >
                                                                {truncateName(source.name, MAX_NAME_DISPLAY)}
                                                            </span>
                                                            {source.type === "website" && source.url && (
                                                                <img
                                                                    src={EXTERNAL_LINK_ICON_SRC}
                                                                    alt=""
                                                                    className="ml-0.5 w-4 h-4 opacity-0 group-hover/link:opacity-100 transition-opacity flex-shrink-0"
                                                                />
                                                            )}
                                                        </span>
                                                        {mgr.isSearchMode && (
                                                            <span
                                                                className={cn(
                                                                    "ml-2 text-[12px] px-2 py-0.5 rounded flex-shrink-0",
                                                                    source.type === "official_account"
                                                                        ? "bg-[#E8F3FF] text-[#165DFF]"
                                                                        : "bg-[#FFF7E8] text-[#F7BA2E]"
                                                                )}
                                                            >
                                                                {source.type === "official_account" ? localize("com_subscription.official_account") : localize("com_subscription.website")}
                                                            </span>
                                                        )}
                                                    </span>
                                                    <div
                                                        className="flex-shrink-0"
                                                        onClick={(e) => e.stopPropagation()}
                                                    >
                                                        <Checkbox
                                                            checked={sel}
                                                            onCheckedChange={() => !dis && mgr.toggleSource(source)}
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
                    {mgr.viewMode === "list" && (
                        <div className="flex justify-between items-center px-4 py-3 border-t border-[#E5E6EB] ">
                            <span className="text-[12px] text-[#86909C]">{localize("com_subscription.total_channel_sources")}{mgr.pendingSources.length}/{MAX_SOURCES}
                            </span>
                            <div className="flex gap-2">
                                <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={async () => {
                                        const confirmed = await confirm({
                                            description: localize("com_subscription.unsaved_edits_confirm_close"),
                                            cancelText: localize("com_subscription.continue_editing"),
                                            confirmText: localize("com_subscription.confirm_close")
                                        });
                                        if (!confirmed) return;
                                        mgr.handleCancel();
                                    }}
                                    className="bg-white border h-8 rounded-[6px] inline-flex items-center justify-center leading-none border-[#E5E6EB]"
                                >
                                    {localize("cancel")}
                                </Button>
                                <Button
                                    size="sm"
                                    onClick={mgr.handleConfirm}
                                    disabled={mgr.pendingSources.length === 0}
                                    className="bg-[#165DFF] h-8 rounded-[6px] inline-flex items-center justify-center leading-none disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    {localize("com_subscription.confirm_add")}
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* 公众号添加失败弹窗 */}
            <AlertDialog
                open={mgr.wechatAddError}
                onOpenChange={(open) => {
                    if (!open) {
                        mgr.setWechatAddError(false);
                    }
                }}
            >
                <AlertDialogContent className="max-w-[420px] rounded-2xl p-0 border-none shadow-[0_8px_24px_rgba(15,23,42,0.18)]">
                    <div className="">
                        <div className="flex items-start justify-between">
                            <div className="flex items-center">
                                <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-[#FEECEC] ml-4 mr-3">
                                    <XCircle className="size-4 text-[#F53F3F]" />
                                </span>
                                <AlertDialogHeader className="text-left mt-6">
                                    <AlertDialogTitle className="text-[16px] font-semibold text-[#1D2129]">{localize("com_subscription.channel_add_failed")}</AlertDialogTitle>
                                    <AlertDialogDescription className="mt-2 text-[14px] text-[#4E5969]">{localize("com_subscription.try_adding_again")}</AlertDialogDescription>
                                </AlertDialogHeader>
                            </div>
                            <button
                                type="button"
                                className="mt-1 text-[#C9CDD4] hover:text-[#4E5969]"
                                onClick={() => mgr.setWechatAddError(false)}
                            >
                                <X className="size-4" />
                            </button>
                        </div>
                    </div>
                    <div className="px-6 pb-4 flex justify-end">
                        <AlertDialogAction
                            onClick={() => mgr.setWechatAddError(false)}
                            className="h-8 px-6 rounded-[6px] inline-flex items-center justify-center leading-none border border-[#E5E6EB] bg-white text-[14px] text-[#4E5969] hover:bg-[#F7F8FA]"
                        >{localize("com_subscription.cancel")}</AlertDialogAction>
                    </div>
                </AlertDialogContent>
            </AlertDialog>

        </div>
    );
}
