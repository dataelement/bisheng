import { Minus, Plus, Search, X, XCircle } from "lucide-react";
import { useState, useEffect, useRef, type MouseEvent } from "react";
import { NotificationSeverity } from "~/common";
import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { truncateName, type InformationSource } from "~/api/channels";
import { cn } from "~/utils";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import useMediaQuery from "~/hooks/useMediaQuery";
import { useSourceManager } from "../hooks/useSourceManager";
import { useConfirm, useToastContext } from "~/Providers";
import { ChannelBookIcon, ChannelLoadingIcon, ChannelRightSmallUpIcon } from "~/components/icons/channels";
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

/** 网站行：非 hover 设备始终下划线 + 外链箭头，点击新开页（与桌面 hover 露出一致的可发现性） */
function WebsiteSourceLink({
    name,
    url,
    maxLen = 20,
    noHover,
    onNavigate,
}: {
    name: string;
    url: string;
    maxLen?: number;
    /** `(hover: none)` 时为主要输入不可悬停的设备 */
    noHover: boolean;
    onNavigate: (e: MouseEvent<HTMLSpanElement>) => void;
}) {
    return (
        <span
            role="link"
            tabIndex={0}
            className={cn(
                "inline-flex max-w-full cursor-pointer items-center align-middle transition-colors",
                noHover
                    ? "text-[#165DFF]"
                    : "group/link text-[#1D2129] hover:text-[#165DFF]",
            )}
            onClick={onNavigate}
            onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    (e.currentTarget as HTMLElement).click();
                }
            }}
        >
            <span
                className={cn(
                    "truncate",
                    noHover ? "underline underline-offset-2" : "hover:underline hover:underline-offset-2",
                )}
            >
                {truncateName(name, maxLen)}
            </span>
            <ChannelRightSmallUpIcon
                className={cn(
                    "ml-0.5 size-4 shrink-0 transition-opacity",
                    noHover ? "text-[#165DFF] opacity-100" : "opacity-0 group-hover/link:opacity-100",
                )}
            />
        </span>
    );
}

interface AddSourceDropdownProps {
    sources: InformationSource[];
    onSourcesChange: (sources: InformationSource[]) => void;
    expanded: boolean;
    onExpandChange: (v: boolean) => void;
    onEnqueueCrawl: (url: string) => void;
    queueInProgressCount: number;
    resetToken?: number;
}

export function AddSourceDropdown({
    sources,
    onSourcesChange,
    expanded,
    onExpandChange,
    onEnqueueCrawl,
    queueInProgressCount,
    resetToken
}: AddSourceDropdownProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const noHoverDevice = useMediaQuery("(hover: none)");
    const mgr = useSourceManager(sources, onSourcesChange, expanded, onExpandChange);
    const confirm = useConfirm();
    const { showToast } = useToastContext();
    const [inputValue, setInputValue] = useState("");
    const [isCollapsedListScrolling, setIsCollapsedListScrolling] = useState(false);
    const collapsedListScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [isExpandedListScrolling, setIsExpandedListScrolling] = useState(false);
    const expandedListScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const rootRef = useRef<HTMLDivElement>(null);
    const expandedPanelRef = useRef<HTMLDivElement>(null);
    const mgrRef = useRef(mgr);
    const isClosingRef = useRef(false);
    mgrRef.current = mgr;

    // 展开面板失焦或点击组件外部时收起，并应用当前勾选（与「确认添加」一致）；弹窗内操作不触发
    useEffect(() => {
        if (!expanded) return;
        isClosingRef.current = false;
        const root = rootRef.current;
        if (!root) return;

        const rootDialog = root.closest('[role="dialog"], [role="alertdialog"]');
        const isInsideOtherDialog = (node: Node | null) => {
            if (!(node instanceof Element)) return false;
            const targetDialog = node.closest('[role="dialog"], [role="alertdialog"]');
            return targetDialog != null && targetDialog !== rootDialog;
        };

        const closePanel = () => {
            if (isClosingRef.current) return;
            isClosingRef.current = true;
            mgrRef.current.handleConfirm();
        };

        const onPointerDown = (e: PointerEvent) => {
            const t = e.target as Node | null;
            if (t && root.contains(t)) return;
            if (isInsideOtherDialog(t)) return;
            closePanel();
        };

        document.addEventListener("pointerdown", onPointerDown, true);
        return () => {
            document.removeEventListener("pointerdown", onPointerDown, true);
        };
    }, [expanded]);

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
        <div ref={rootRef} className="relative">
            {/* 没点击时：触发区+已选列表 同一灰色整体 */}
            {!expanded && (
                <div
                    className="flex max-h-[480px] flex-col overflow-hidden rounded-lg border border-[#E5E6EB]"
                    role="button"
                    tabIndex={0}
                    onClick={() => onExpandChange(true)}
                    onKeyDown={(e) => e.key === "Enter" && onExpandChange(true)}
                >
                    <div className="flex shrink-0 items-center gap-2 bg-[#F7F7F7] px-4 py-3">
                        <Plus className="size-4 flex-shrink-0 text-[#86909C]" />
                        <span className="flex-1 text-[14px] text-[#86909C] text-left">{localize("com_subscription.add_official_accounts_and_webpages")}</span>
                        <span className="flex-shrink-0 text-[12px] text-[#86909C]">
                            {sources.length}/{MAX_SOURCES}
                        </span>
                    </div>
                    {sources.length > 0 && (
                        <div
                            className="scroll-on-scroll overflow-y-auto border-t border-[#E5E6EB] bg-[#FBFBFB]"
                            onScroll={handleCollapsedListScroll}
                            data-scrolling={isCollapsedListScrolling ? "true" : "false"}
                        >
                            {[...sources].reverse().map((s, idx, arr) => (
                                <div key={s.id}>
                                    <div
                                        className="flex items-center gap-3 py-2 px-4 hover:bg-[#EEEFF1]"
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
                                            {s.type === "website" && s.url ? (
                                                <WebsiteSourceLink
                                                    name={s.name}
                                                    url={s.url}
                                                    noHover={noHoverDevice}
                                                    onNavigate={(e) => {
                                                        e.stopPropagation();
                                                        window.open(s.url, "_blank");
                                                    }}
                                                />
                                            ) : (
                                                <span className="truncate">{truncateName(s.name)}</span>
                                            )}
                                            <span className="ml-2 flex-shrink-0 rounded border border-[#165DFF] px-0.5 text-[11px] text-[#165DFF]">
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
                                    {idx < arr.length - 1 && (
                                        <div
                                            className="mx-[12px] border-b border-dashed border-[#D9D9D9]"
                                            aria-hidden
                                        />
                                    )}
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
                <div
                    ref={expandedPanelRef}
                    className={cn(
                        "absolute left-0 right-0 top-0 z-[220] flex flex-col overflow-hidden rounded-lg border border-[#E5E6EB] bg-white shadow-[0_4px_16px_rgba(0,0,0,0.12)]",
                        "h-[440px] min-w-[400px]",
                        isH5 && "h-[min(70dvh,560px)] min-w-0 max-w-full rounded-[8px]"
                    )}
                >
                    <div className="flex shrink-0 items-center gap-2 border-b border-[#E5E6EB] pb-0 mb-2">
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
                        <div className="mx-3 shrink-0 border-b border-[#E5E6EB]">
                            <div className="flex gap-4 px-1">
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
                        </div>
                    )}
                    <div
                        className="min-h-0 flex-1 overflow-y-auto scroll-on-scroll"
                        onScroll={handleExpandedListScroll}
                        data-scrolling={isExpandedListScrolling ? "true" : "false"}
                    >
                        {mgr.viewMode === "noResultNonUrl" && (
                            <div className="flex min-h-full flex-col items-center justify-center px-4 py-8 text-center">
                                <div className="mb-4 rounded-full p-3">
                                    <ChannelBookIcon className="w-[120px] h-[120px] mb-5" />
                                </div>
                                <p className="text-[14px] leading-6 text-[#4E5969] whitespace-pre-line">
                                    {localize("com_subscription.no_source_collected") ||
                                        localize("com_subscription.source_not_indexed_try_full_url")}
                                </p>
                            </div>
                        )}
                        {mgr.viewMode === "noResultUrl" && (
                            <div className="flex min-h-full flex-col items-center justify-center px-4 py-8 text-center">
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
                                        className="h-8 rounded-[6px] min-w-[74px] inline-flex items-center justify-center leading-none border border-[#E5E6EB] bg-white text-[14px] !font-normal text-[#4E5969]"
                                    >
                                        {localize("com_subscription.do_not_crawl")}
                                    </Button>
                                    <Button
                                        onClick={() => {
                                            // 50 上限：已选 + 队列在跑的 = 阻断
                                            if (mgr.pendingSources.length + queueInProgressCount >= MAX_SOURCES) {
                                                showToast({
                                                    message: localize("com_subscription.maximum_channel_source")
                                                        || `已达频道 ${MAX_SOURCES} 个信源上限，无法再爬取`,
                                                    severity: NotificationSeverity.WARNING,
                                                });
                                                return;
                                            }
                                            onEnqueueCrawl(mgr.searchKeyword.trim());
                                            // 清搜索回 list 视图，并切到「网站」tab
                                            setInputValue("");
                                            mgr.handleClearSearch();
                                            mgr.setActiveTab("website");
                                        }}
                                        className="h-8 rounded-[6px] min-w-[74px] inline-flex items-center justify-center leading-none text-[14px] !font-normal text-white bg-[#165DFF] hover:bg-[#4080FF]"
                                    >
                                        {localize("com_subscription.confirm_crawl")}
                                    </Button>
                                </div>
                            </div>
                        )}
                        {mgr.viewMode === "wechatProcessing" && (
                            <div className="flex min-h-full flex-col items-center justify-center px-4 py-8 text-center">
                                <div className="mb-4">
                                    <ChannelLoadingIcon className="w-[120px] h-[120px]" />
                                </div>
                                <p className="text-[14px] text-[#4E5969] mb-5">
                                    {localize("com_subscription.detect_wechat_link") || localize("com_subscription.official_account_link_detected_adding")}
                                </p>
                                <Button
                                    variant="secondary"
                                    onClick={mgr.handleClearSearch}
                                    className="h-8 rounded-[6px] min-w-[84px] inline-flex items-center justify-center leading-none text-[14px] !font-normal border border-[#E5E6EB] bg-white text-[#4E5969]"
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
                                                        "grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 cursor-pointer",
                                                        dis && "opacity-60 cursor-not-allowed",
                                                        sel && "bg-[#E8F3FF]"
                                                    )}
                                                >
                                                    <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-[#F2F3F5]">
                                                        {source.avatar ? (
                                                            <img src={source.avatar} alt="" className="w-full h-full object-cover" />
                                                        ) : (
                                                            <div className="w-full h-full flex items-center justify-center text-[12px] text-[#86909C]">
                                                                {source.name[0]}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <span className="min-w-0 truncate text-[14px] text-[#1D2129]">
                                                        {source.type === "website" && source.url ? (
                                                            <WebsiteSourceLink
                                                                name={source.name}
                                                                url={source.url}
                                                                maxLen={MAX_NAME_DISPLAY}
                                                                noHover={noHoverDevice}
                                                                onNavigate={(e) => {
                                                                    e.stopPropagation();
                                                                    window.open(source.url, "_blank");
                                                                }}
                                                            />
                                                        ) : (
                                                            <span className="truncate">
                                                                {truncateName(source.name, MAX_NAME_DISPLAY)}
                                                            </span>
                                                        )}
                                                        {mgr.isSearchMode && (
                                                            <span
                                                                className="ml-2 flex-shrink-0 rounded border border-[#165DFF] px-0.5 text-[11px] text-[#165DFF]"
                                                            >
                                                                {source.type === "official_account"
                                                                    ? localize("com_subscription.official_account")
                                                                    : localize("com_subscription.website")}
                                                            </span>
                                                        )}
                                                    </span>
                                                    <div
                                                        className="flex h-6 w-6 flex-shrink-0 items-center justify-center"
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
                        <div className="relative z-[221] flex shrink-0 items-center justify-between border-t border-[#E5E6EB] bg-white px-4 py-3 touch-mobile:flex-col touch-mobile:items-stretch touch-mobile:gap-2">
                            <span className="text-[12px] text-[#86909C]">{localize("com_subscription.total_channel_sources")}{mgr.pendingSources.length}/{MAX_SOURCES}
                            </span>
                            <div className="flex gap-2 touch-mobile:w-full">
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
                                    className="border border-[#E5E6EB] bg-white h-8 rounded-[6px] inline-flex items-center justify-center leading-none text-[14px] !font-normal text-[#4E5969] touch-mobile:flex-1"
                                >
                                    {localize("cancel")}
                                </Button>
                                <Button
                                    size="sm"
                                    onClick={mgr.handleConfirm}
                                    disabled={mgr.pendingSources.length === 0}
                                    className="bg-[#165DFF] h-8 rounded-[6px] inline-flex items-center justify-center leading-none text-[14px] !font-normal text-white disabled:opacity-50 disabled:cursor-not-allowed touch-mobile:flex-1"
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
                            className="h-8 px-6 rounded-[6px] inline-flex items-center justify-center leading-none border border-[#E5E6EB] bg-white text-[14px] !font-normal text-[#4E5969] hover:bg-[#F7F8FA]"
                        >{localize("com_subscription.cancel")}</AlertDialogAction>
                    </div>
                </AlertDialogContent>
            </AlertDialog>

        </div>
    );
}
