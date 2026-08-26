import { Outlined } from "bisheng-icons";
import { useState, useEffect, useRef, type MouseEvent } from "react";
import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { truncateName, type InformationSource } from "~/api/channels";
import { cn } from "~/utils";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useSourceManager } from "../hooks/useSourceManager";
import { useConfirm } from "~/Providers";
import { ChannelRightSmallUpIcon } from "~/components/icons/channels";
import { ListWebLinkIllustration, EmptyStateIllustration, CrawlingIllustration } from "~/components/illustrations";
import { WechatLinkHint } from "./WechatLinkHint";

const MAX_SOURCES = 50;
const MAX_NAME_DISPLAY = 20;

/** 网站行：文本只展示（无超链接样式与点击），跳转入口收口到末尾箭头按钮上；箭头仅 hover 时露出 */
function WebsiteSourceLink({
    name,
    url: _url,
    maxLen = 20,
    onNavigate,
}: {
    name: string;
    url: string;
    maxLen?: number;
    onNavigate: (e: MouseEvent<HTMLElement>) => void;
}) {
    return (
        <span className="group/link inline-flex max-w-full items-center align-middle text-[#1D2129]">
            {/* External-link source: name turns brand blue on hover and stays blue (does not follow theme). */}
            <span className="truncate transition-colors group-hover/link:text-[#335CFF]">
                {truncateName(name, maxLen)}
            </span>
            <button
                type="button"
                aria-label="open external link"
                onClick={onNavigate}
                onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        (e.currentTarget as HTMLElement).click();
                    }
                }}
                className="ml-0.5 inline-flex size-4 shrink-0 items-center justify-center text-[#335CFF] cursor-pointer opacity-0 transition-opacity group-hover/link:opacity-100"
            >
                <ChannelRightSmallUpIcon className="size-4 shrink-0" />
            </button>
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
    resetToken
}: AddSourceDropdownProps) {
    const localize = useLocalize();
    const isH5 = usePrefersMobileLayout();
    const mgr = useSourceManager(sources, onSourcesChange, expanded, onExpandChange);
    const confirm = useConfirm();
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
            if (targetDialog) return targetDialog !== rootDialog;
            // A modal's full-screen mask is a SIBLING of its [role=alertdialog]
            // node inside the same portal layer, so `closest` can never see it.
            // Without this, clicking the mask of the stacked "link unrecognized"
            // confirm read as "clicked outside" and collapsed this panel — which
            // looked like the click had passed through the mask.
            const layerDialog = node.parentElement?.querySelector('[role="dialog"], [role="alertdialog"]');
            return layerDialog != null && layerDialog !== rootDialog;
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
                        <Outlined.Plus className="size-4 flex-shrink-0 text-[#999999]" />
                        <span className="flex-1 text-left text-[14px] text-[#999999]">{localize("com_subscription.add_official_accounts_and_webpages")}</span>
                        <span className="flex-shrink-0 text-[12px] text-[#999999]">
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
                                                    onNavigate={(e) => {
                                                        e.stopPropagation();
                                                        window.open(s.url, "_blank");
                                                    }}
                                                />
                                            ) : (
                                                <span className="truncate">{truncateName(s.name)}</span>
                                            )}
                                            <span className="ml-2 flex-shrink-0 rounded border border-blue-500 px-0.5 text-[11px] text-blue-500">
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
                                                <span className="h-px w-2 bg-[#F53F3F]" />
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
                    <span className="flex-shrink-0 text-[12px] text-[#999999]">
                        {mgr.pendingSources.length}/{MAX_SOURCES}
                    </span>
                </div>
            )}

            {/* 添加时：输入框+Tab+列表 同一整体，浮在表单之上，实时搜索 */}
            {/* Page-level dropdown, so it must stay UNDER everything that is meant
                to cover it: portalled tooltips (z-50) and the modal layer
                (Dialog z-100 / AlertDialog z-110). It used to sit at z-[220] —
                a leftover from when this panel lived inside a drawer — which put
                it above the confirm dialog and above its own "where to copy the
                link" tooltip. Only the crawl-queue dropdown (z-30) outranks it. */}
            {expanded && (
                <div
                    ref={expandedPanelRef}
                    className={cn(
                        "absolute left-0 right-0 top-0 z-20 flex flex-col overflow-hidden rounded-lg border border-[#E5E6EB] bg-white shadow-[0_4px_16px_rgba(0,0,0,0.12)]",
                        "h-[440px] min-w-[400px]",
                        isH5 && "h-[min(70dvh,560px)] min-w-0 max-w-full rounded-lg"
                    )}
                >
                    <div className="flex shrink-0 items-center gap-2 border-b border-[#E5E6EB] pb-0 mb-2">
                        <div className="relative flex-1 rounded-lg m-1">
                            <Outlined.Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
                            <Input
                                value={inputValue}
                                onChange={(e) => setInputValue(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter") {
                                        // Submit, not just "set the keyword": pressing Enter
                                        // again on an unchanged link has to retry it.
                                        mgr.submitSearch(inputValue.trim());
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
                                    <Outlined.Close className="size-4" />
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
                                            ? "text-blue-500 border-blue-500"
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
                                            ? "text-blue-500 border-blue-500"
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
                                <div className="mb-4">
                                    <ListWebLinkIllustration className="mx-auto block w-[120px] h-[120px]" />
                                </div>
                                {/* One line: the sentence reads as a single
                                    instruction, so it is kept unwrapped and the
                                    panel scrolls rather than breaking it. Below
                                    the H5 breakpoint it must wrap instead —
                                    unwrapped it needs ~520px, which pushes the
                                    tappable phrase off-screen behind a
                                    horizontal scroll on a phone. */}
                                <WechatLinkHint
                                    className="max-w-full whitespace-nowrap max-[767px]:whitespace-normal"
                                    sentenceKey="com_subscription.no_source_collected"
                                    labelKey="com_subscription.wechat_article_link_label"
                                />
                            </div>
                        )}
                        {mgr.viewMode === "noResultUrl" && (
                            <div className="flex min-h-full flex-col items-center justify-center px-4 py-8 text-center">
                                <div className="mb-4">
                                    <EmptyStateIllustration className="mx-auto block w-[120px] h-[120px]" />
                                </div>
                                <p className="text-[14px] font-normal text-[#999999] mb-5">
                                    {localize("com_subscription.website_not_indexed") || localize("com_subscription.website_not_in_database_crawl")}
                                </p>
                                <div className="flex gap-3 justify-center">
                                    <Button
                                        variant="secondary"
                                        onClick={mgr.handleClearSearch}
                                        className="h-8 rounded-md min-w-[74px] inline-flex items-center justify-center leading-none border border-[#E5E6EB] bg-white text-[14px] !font-normal text-[#4E5969]"
                                    >
                                        {localize("com_subscription.do_not_crawl")}
                                    </Button>
                                    <Button
                                        onClick={() => {
                                            // No front-end source-count cap: the backend / external API-key
                                            // quota is the source of truth and rejects over-quota subscriptions.
                                            onEnqueueCrawl(mgr.searchKeyword.trim());
                                            // 清搜索回 list 视图，并切到「网站」tab
                                            setInputValue("");
                                            mgr.handleClearSearch();
                                            mgr.setActiveTab("website");
                                        }}
                                        className="h-8 rounded-md min-w-[74px] inline-flex items-center justify-center leading-none text-[14px] !font-normal text-white bg-blue-500 hover:bg-blue-400 btn-brand-primary"
                                    >
                                        {localize("com_subscription.confirm_crawl")}
                                    </Button>
                                </div>
                            </div>
                        )}
                        {mgr.viewMode === "wechatProcessing" && (
                            <div className="flex min-h-full flex-col items-center justify-center px-4 py-8 text-center">
                                <div className="mb-4">
                                    <CrawlingIllustration className="w-[120px] h-[120px]" />
                                </div>
                                {mgr.wechatLinkFailed ? (
                                    <WechatLinkHint
                                        className="mb-5 max-w-full whitespace-nowrap max-[767px]:whitespace-normal"
                                        sentenceKey="com_subscription.wechat_link_retry_hint"
                                        labelKey="com_subscription.wechat_link_label"
                                    />
                                ) : (
                                    <p className="text-[14px] font-normal text-[#999999] mb-5">
                                        {localize("com_subscription.detect_wechat_link") || localize("com_subscription.official_account_link_detected_adding")}
                                    </p>
                                )}
                                <Button
                                    variant="secondary"
                                    onClick={mgr.handleClearSearch}
                                    className="h-8 rounded-md min-w-[84px] inline-flex items-center justify-center leading-none text-[14px] !font-normal border border-[#E5E6EB] bg-white text-[#4E5969]"
                                >
                                    {localize("com_subscription.do_not_add")}
                                </Button>
                            </div>
                        )}
                        {mgr.viewMode === "list" && (
                            <>
                                {displayList.length === 0 ? (
                                    <div className="flex min-h-full items-center justify-center p-8 text-center text-[14px] text-[#999999]">{localize("com_subscription.no_data")}</div>
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
                                                        sel && "bg-[#FBFBFB]"
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
                                                                className="ml-2 flex-shrink-0 rounded border border-blue-500 px-0.5 text-[11px] text-blue-500"
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
                                                            className="rounded border-[#C9CDD4] data-[state=checked]:bg-blue-500 data-[state=checked]:border-blue-500"
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
                        <div className="relative z-10 flex shrink-0 items-center justify-between border-t border-[#E5E6EB] bg-white px-4 py-3 touch-mobile:flex-col touch-mobile:items-stretch touch-mobile:gap-2">
                            <span className="text-[12px] text-[#999999]">{localize("com_subscription.total_channel_sources")}{mgr.pendingSources.length}/{MAX_SOURCES}
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
                                    className="border border-[#E5E6EB] bg-white h-8 rounded-md inline-flex items-center justify-center leading-none text-[14px] !font-normal text-[#4E5969] touch-mobile:flex-1"
                                >
                                    {localize("cancel")}
                                </Button>
                                <Button
                                    size="sm"
                                    onClick={mgr.handleConfirm}
                                    disabled={mgr.pendingSources.length === 0}
                                    className="bg-blue-500 h-8 rounded-md inline-flex items-center justify-center leading-none text-[14px] !font-normal text-white disabled:opacity-50 disabled:cursor-not-allowed touch-mobile:flex-1 btn-brand-primary"
                                >
                                    {localize("com_subscription.confirm_add")}
                                </Button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
