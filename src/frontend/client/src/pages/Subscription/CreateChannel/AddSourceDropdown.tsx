import { Outlined } from "bisheng-icons";
import { useState, useEffect, useRef, type MouseEvent } from "react";
import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import { SearchInput } from "@bisheng/ui";
import { truncateName, type InformationSource } from "~/api/channels";
import { cn } from "~/utils";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useSourceManager } from "../hooks/useSourceManager";
import { useConfirm } from "~/Providers";
import { ChannelRightSmallUpIcon } from "~/components/icons/channels";
import { ListWebLinkIllustration, EmptyStateIllustration, CrawlingIllustration } from "~/components/illustrations";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
// Imported as a module (not a /public URL) so the bundler resolves it against
// the app's base path and fingerprints it — no env-var lookup at render time.
import wechatCopyLinkGuide from "./wechat-copy-link-guide.png";

const MAX_NAME_DISPLAY = 20;

/**
 * A sentence with one highlighted phrase that hovers open the "where do I copy
 * a WeChat article link from" tooltip. Used both after a link fails to resolve
 * and when a search turns up nothing — each passes its own copy, since the two
 * moments word the advice differently.
 *
 * The sentence is one i18n key with a `{{link}}` placeholder so translators keep
 * control of word order; it is split back apart on the localized phrase.
 */
export function WechatLinkHint({
    className,
    sentenceKey,
    labelKey,
}: {
    className?: string;
    sentenceKey: string;
    labelKey: string;
}) {
    const localize = useLocalize();
    const linkLabel = localize(labelKey);
    const sentence = localize(sentenceKey, { link: linkLabel });
    const splitAt = sentence.indexOf(linkLabel);

    const highlighted = (
        <Tooltip>
            <TooltipTrigger asChild>
                {/* mx-1 gives the highlighted phrase breathing room from the grey
                    text on both sides; CJK copy has no natural word spacing. */}
                <span className="mx-1 cursor-pointer text-blue-500 no-underline">{linkLabel}</span>
            </TooltipTrigger>
            <TooltipContent
                side="top"
                className="w-[280px] max-w-[280px] rounded-md border-none bg-white p-3 text-left text-xs leading-5 text-text-3 shadow-[0_4px_16px_rgba(0,0,0,0.12)]"
                arrowClassName="bg-white fill-white"
            >
                <img src={wechatCopyLinkGuide} alt="" className="mx-auto mb-2 w-[160px] rounded" />
                {/* Size/colour live on the <p> itself, matching the sentence that
                    owns the trigger — inheriting from the panel lets the panel's
                    own text-* classes compete with them. */}
                <p className="text-[12px] leading-5 text-text-3">
                    {localize("com_subscription.wechat_link_copy_tip")}
                </p>
            </TooltipContent>
        </Tooltip>
    );

    // Defensive: a translation that dropped the placeholder still renders readably.
    if (splitAt === -1) {
        return <p className={cn("text-[14px] font-normal text-text-3", className)}>{sentence}</p>;
    }

    return (
        <p className={cn("text-[14px] font-normal leading-[22px] text-text-3", className)}>
            {/* Trim the seam so `mx-1` is the only gap — languages that already
                separate words with spaces would otherwise read as a double space. */}
            {sentence.slice(0, splitAt).replace(/\s+$/, "")}
            {highlighted}
            {sentence.slice(splitAt + linkLabel.length).replace(/^\s+/, "")}
        </p>
    );
}

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
        <span className="group/link inline-flex max-w-full items-center align-middle text-text-1">
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
                    className="flex max-h-[480px] flex-col overflow-hidden rounded-lg border border-border-base"
                    role="button"
                    tabIndex={0}
                    onClick={() => onExpandChange(true)}
                    onKeyDown={(e) => e.key === "Enter" && onExpandChange(true)}
                >
                    <div className="flex shrink-0 items-center gap-2 bg-fill-1 px-4 py-3">
                        <Outlined.Plus className="size-4 flex-shrink-0 text-text-3" />
                        <span className="flex-1 text-left text-[14px] text-text-3">{localize("com_subscription.add_official_accounts_and_webpages")}</span>
                        <span className="flex-shrink-0 text-[12px] text-text-3">
                            {localize("com_subscription.channel_selected_sources_count", { 0: sources.length })}
                        </span>
                    </div>
                    {sources.length > 0 && (
                        <div
                            className="scroll-on-scroll overflow-y-auto border-t border-border-base bg-[#FBFBFB]"
                            onScroll={handleCollapsedListScroll}
                            data-scrolling={isCollapsedListScrolling ? "true" : "false"}
                        >
                            {[...sources].reverse().map((s, idx, arr) => (
                                <div key={s.id}>
                                    <div
                                        className="flex items-center gap-3 py-2 px-4 hover:bg-[#EEEFF1]"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <div className="w-8 h-8 rounded-full bg-fill-3 flex-shrink-0 overflow-hidden">
                                            {s.avatar ? (
                                                <img src={s.avatar} alt="" className="w-full h-full object-cover" />
                                            ) : (
                                                <div className="w-full h-full flex items-center justify-center text-[12px] text-text-3">
                                                    {s.name[0]}
                                                </div>
                                            )}
                                        </div>
                                        <span className="flex-1 text-[14px] text-text-1 truncate">
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
                    <span className="flex-shrink-0 text-[12px] text-text-3">
                        {localize("com_subscription.channel_selected_sources_count", { 0: mgr.pendingSources.length })}
                    </span>
                </div>
            )}

            {/* Keep the source panel below the global confirmation layer (z-110). */}
            {expanded && (
                <div
                    ref={expandedPanelRef}
                    className={cn(
                        "absolute left-0 right-0 top-0 z-[100] flex flex-col overflow-hidden rounded-lg border border-border-base bg-white shadow-[0_4px_16px_rgba(0,0,0,0.12)]",
                        "h-[440px] min-w-[400px]",
                        isH5 && "h-[min(70dvh,560px)] min-w-0 max-w-full rounded-lg"
                    )}
                >
                    <div className="flex shrink-0 items-center gap-2 border-b border-border-base pb-0 mb-2">
                        {/* Spec SearchInput in `borderless` form — the panel draws the
                            chrome, so the field shows no border and no focus ring (design
                            call, 2026-08-25). onClear also resets the manager's search
                            state, which the built-in clear alone would not do. Enter
                            submits (not just sets the keyword) so an unchanged link can
                            be retried. */}
                        <SearchInput
                            borderless
                            className="m-1 flex-1"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onSearch={() => mgr.submitSearch(inputValue.trim())}
                            placeholder={localize("com_subscription.enter_official_account")}
                            clearLabel={localize("com_ui_clear")}
                            onClear={() => mgr.handleClearSearch()}
                            autoFocus
                        />
                    </div>
                    {/* 仅非搜索时显示 Tab；搜索时混合展示，类型在名称后 */}
                    {!mgr.isSearchMode && (
                        <div className="mx-3 shrink-0 border-b border-border-base">
                            <div className="flex gap-4 px-1">
                                <button
                                    type="button"
                                    onClick={() => mgr.setActiveTab("official_account")}
                                    className={cn(
                                        "pb-2 text-[14px] font-medium border-b-2 -mb-px",
                                        mgr.activeTab === "official_account"
                                            ? "text-blue-500 border-blue-500"
                                            : "text-text-3 border-transparent"
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
                                            : "text-text-3 border-transparent"
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
                                    panel scrolls rather than breaking it. */}
                                <WechatLinkHint
                                    className="max-w-full whitespace-nowrap"
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
                                <p className="text-[14px] font-normal text-text-3 mb-5">
                                    {localize("com_subscription.website_not_indexed") || localize("com_subscription.website_not_in_database_crawl")}
                                </p>
                                <div className="flex gap-3 justify-center">
                                    <Button
                                        variant="secondary"
                                        onClick={mgr.handleClearSearch}
                                        className="h-8 rounded-md min-w-[74px] inline-flex items-center justify-center leading-none border border-border-base bg-white text-[14px] !font-normal text-text-2"
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
                                        className="mb-5 max-w-full whitespace-nowrap"
                                        sentenceKey="com_subscription.wechat_link_retry_hint"
                                        labelKey="com_subscription.wechat_link_label"
                                    />
                                ) : (
                                    <p className="text-[14px] font-normal text-text-3 mb-5">
                                        {localize("com_subscription.detect_wechat_link") || localize("com_subscription.official_account_link_detected_adding")}
                                    </p>
                                )}
                                <Button
                                    variant="secondary"
                                    onClick={mgr.handleClearSearch}
                                    className="h-8 rounded-md min-w-[84px] inline-flex items-center justify-center leading-none text-[14px] !font-normal border border-border-base bg-white text-text-2"
                                >
                                    {localize("com_subscription.do_not_add")}
                                </Button>
                            </div>
                        )}
                        {mgr.viewMode === "list" && (
                            <>
                                {displayList.length === 0 ? (
                                    <div className="flex min-h-full items-center justify-center p-8 text-center text-[14px] text-text-3">{localize("com_subscription.no_data")}</div>
                                ) : (
                                    <div className="">
                                        {displayList.map((source) => {
                                            const sel = mgr.selectedIds.has(source.id);
                                            const dis = !sel && mgr.isSourceQuotaBlocked(source.id);
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
                                                    <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center overflow-hidden rounded-full bg-fill-2">
                                                        {source.avatar ? (
                                                            <img src={source.avatar} alt="" className="w-full h-full object-cover" />
                                                        ) : (
                                                            <div className="w-full h-full flex items-center justify-center text-[12px] text-text-3">
                                                                {source.name[0]}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <span className="min-w-0 truncate text-[14px] text-text-1">
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
                                                            className="rounded border-border-deep data-[state=checked]:bg-blue-500 data-[state=checked]:border-blue-500"
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
                        <div className="relative z-[221] flex shrink-0 items-center justify-between border-t border-border-base bg-white px-4 py-3 touch-mobile:flex-col touch-mobile:items-stretch touch-mobile:gap-2">
                            <span className="flex flex-col gap-0.5 text-[12px] text-text-3">
                                <span>{localize("com_subscription.channel_selected_sources_count", { 0: mgr.pendingSources.length })}</span>
                                <span>
                                    {localize("com_subscription.info_source_quota_usage", {
                                        0: mgr.sourceQuotaUsed,
                                        1: mgr.sourceQuotaLimit === -1 ? localize("com_storage_quota.unlimited") : mgr.sourceQuotaLimit,
                                    })}
                                </span>
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
                                    className="border border-border-base bg-white h-8 rounded-md inline-flex items-center justify-center leading-none text-[14px] !font-normal text-text-2 touch-mobile:flex-1"
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
