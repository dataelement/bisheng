import { useEffect, useMemo, useRef, useState } from "react";
import { type InformationSource, type SourceType } from "~/api/channels";
import {
    ChannelBusinessType,
    listManagerSourcesApi,
    searchManagerSourcesApi,
    type ManagerSource,
    addWechatSourceApi
} from "~/api/channels";
import { useLocalize } from "~/hooks";

const MAX_SOURCES = 50;
const PAGE_SIZE = 20;

function looksLikeUrl(s: string): boolean {
    const t = s.trim();
    // 支持：
    // - 带协议的完整 URL：https://example.com/xxx
    // - 不带协议的域名/路径：home.cofco.com 或 home.cofco.com/path
    return (
        /^https?:\/\//i.test(t) ||
        /^([a-z0-9-]+\.)+[a-z]{2,}(\/[^\s]*)?$/i.test(t)
    );
}

function looksLikeWechatArticleUrl(s: string): boolean {
    return s.trim().toLowerCase().includes("mp.weixin.qq.com/");
}

export type ViewMode = "list" | "noResultNonUrl" | "noResultUrl" | "wechatProcessing";

export function useSourceManager(
    sources: InformationSource[],
    onSourcesChange: (sources: InformationSource[]) => void,
    expanded: boolean,
    onExpandChange: (v: boolean) => void
) {
    const [activeTab, setActiveTab] = useState<SourceType>("official_account");
    const [searchKeyword, setSearchKeyword] = useState("");
    const [pendingSources, setPendingSources] = useState<InformationSource[]>([]);
    const [wechatSources, setWechatSources] = useState<InformationSource[]>([]);
    const [websiteSources, setWebsiteSources] = useState<InformationSource[]>([]);
    const [loadingSources, setLoadingSources] = useState(false);
    const [listPageMap, setListPageMap] = useState<Record<ChannelBusinessType, number>>({
        wechat: 1,
        website: 1,
    });
    const [listHasMoreMap, setListHasMoreMap] = useState<Record<ChannelBusinessType, boolean>>({
        wechat: true,
        website: true,
    });
    const [searchPage, setSearchPage] = useState(1);
    const [searchHasMore, setSearchHasMore] = useState(true);
    const prevExpanded = useRef(false);
    const processingWechatRef = useRef("");
    const wechatRequestTokenRef = useRef(0);
    const wechatAbortRef = useRef<AbortController | null>(null);
    const [wechatAddError, setWechatAddError] = useState(false);
    const localize = useLocalize();

    const normalizeUrlForSearch = (value?: string) => {
        if (!value) return "";
        return value.trim().toLowerCase().replace(/\/+$/, "");
    };

    const abortWechatRequest = () => {
        wechatAbortRef.current?.abort();
        wechatAbortRef.current = null;
    };

    // Sync pending sources when panel opens
    useEffect(() => {
        if (expanded && !prevExpanded.current) setPendingSources([...sources]);
        prevExpanded.current = expanded;
    }, [expanded, sources]);

    // 爬取/新增的信源会先进入父级 sources → pendingSources，可能尚未出现在管理端搜索接口结果里；
    // 合并进展示列表，否则 URL 搜索仍会判定「无结果」而卡在「网站尚未入库」页。
    const mergedWechat = useMemo(() => {
        const ids = new Set(wechatSources.map((s) => s.id));
        const extra = pendingSources.filter(
            (s) => s.type === "official_account" && !ids.has(s.id)
        );
        return extra.length ? [...wechatSources, ...extra] : wechatSources;
    }, [wechatSources, pendingSources]);

    const mergedWebsite = useMemo(() => {
        const ids = new Set(websiteSources.map((s) => s.id));
        const extra = pendingSources.filter((s) => s.type === "website" && !ids.has(s.id));
        return extra.length ? [...websiteSources, ...extra] : websiteSources;
    }, [websiteSources, pendingSources]);

    const filteredSources = useMemo(() => {
        const kw = searchKeyword.trim().toLowerCase();
        const kwNorm = normalizeUrlForSearch(searchKeyword);
        if (!kw) {
            return activeTab === "official_account" ? mergedWechat : mergedWebsite;
        }
        const combined = [...mergedWechat, ...mergedWebsite];
        return combined.filter(
            (s) =>
                s.name.toLowerCase().includes(kw) ||
                (s.url && (
                    s.url.toLowerCase().includes(kw) ||
                    normalizeUrlForSearch(s.url).includes(kwNorm)
                ))
        );
    }, [activeTab, searchKeyword, mergedWechat, mergedWebsite]);

    const isSearchMode = searchKeyword.trim().length > 0;
    const workingSources = expanded ? pendingSources : sources;
    const selectedIds = new Set(workingSources.map((s) => s.id));
    const canSelectMore = workingSources.length < MAX_SOURCES;
    const isAtLimit = workingSources.length >= MAX_SOURCES;

    // 当外部 sources 在面板展开期间新增时（例如通过爬取新网址信源），
    // 自动将新增的信源合并进 pendingSources，并保持选中态。
    useEffect(() => {
        if (!expanded) return;
        if (!sources || sources.length === 0) return;
        setPendingSources((prev) => {
            const map = new Map(prev.map((s) => [s.id, s]));
            let changed = false;
            for (const s of sources) {
                if (!map.has(s.id)) {
                    map.set(s.id, s);
                    changed = true;
                }
            }
            return changed ? Array.from(map.values()) : prev;
        });
    }, [expanded, sources]);

    const viewMode: ViewMode = useMemo(() => {
        if (!searchKeyword.trim()) return "list";
        if (filteredSources.length > 0) return "list";
        if (looksLikeWechatArticleUrl(searchKeyword)) return "wechatProcessing";
        return looksLikeUrl(searchKeyword) ? "noResultUrl" : "noResultNonUrl";
    }, [searchKeyword, filteredSources.length]);

    // Load source list from API
    useEffect(() => {
        if (!expanded) return;
        if (searchKeyword.trim()) return; 
        const load = async (business_type: ChannelBusinessType) => {
            setLoadingSources(true);
            try {
                const res = await listManagerSourcesApi({ business_type, page: 1, page_size: PAGE_SIZE });
                const mapped: InformationSource[] = (res.sources || []).map((s: ManagerSource) => ({
                    id: s.id,
                    name: s.name,
                    avatar: s.icon,
                    url: s.original_url,
                    type: s.business_type === "wechat" ? "official_account" : "website"
                }));
                if (business_type === "wechat") setWechatSources(mapped);
                else setWebsiteSources(mapped);
                setListPageMap((prev) => ({ ...prev, [business_type]: 1 }));
                setListHasMoreMap((prev) => ({
                    ...prev,
                    [business_type]: res.total > mapped.length,
                }));
            } catch {
                // Silent fail, keep current list
            } finally {
                setLoadingSources(false);
            }
        };
        const currentType: ChannelBusinessType =
            activeTab === "official_account" ? "wechat" : "website";
        load(currentType);
    }, [expanded, activeTab, searchKeyword]);

    useEffect(() => {
        if (!expanded) return;
        const kw = searchKeyword.trim();
        if (!kw) return;

        const load = async () => {
            setLoadingSources(true);
            try {
                const res = await searchManagerSourcesApi({
                    keyword: kw,
                    page: 1,
                    page_size: PAGE_SIZE,
                });
                const mapped: InformationSource[] = (res.sources || []).map((s: ManagerSource) => ({
                    id: s.id,
                    name: s.name,
                    avatar: s.icon,
                    url: s.original_url,
                    type: s.business_type === "wechat" ? "official_account" : "website"
                }));
                const wechat = mapped.filter((s) => s.type === "official_account");
                const website = mapped.filter((s) => s.type === "website");
                setWechatSources(wechat);
                setWebsiteSources(website);
                setSearchPage(1);
                setSearchHasMore(res.total > mapped.length);
            } catch {
                // 出错时保持现有列表
            } finally {
                setLoadingSources(false);
            }
        };

        load();
    }, [expanded, searchKeyword]);

    const loadMoreSources = async () => {
        if (!expanded || loadingSources) return;
        const kw = searchKeyword.trim();

        if (kw) {
            if (!searchHasMore) return;
            const nextPage = searchPage + 1;
            setLoadingSources(true);
            try {
                const res = await searchManagerSourcesApi({
                    keyword: kw,
                    page: nextPage,
                    page_size: PAGE_SIZE,
                });
                const mapped: InformationSource[] = (res.sources || []).map((s: ManagerSource) => ({
                    id: s.id,
                    name: s.name,
                    avatar: s.icon,
                    url: s.original_url,
                    type: s.business_type === "wechat" ? "official_account" : "website",
                }));
                const wechat = mapped.filter((s) => s.type === "official_account");
                const website = mapped.filter((s) => s.type === "website");
                setWechatSources((prev) => {
                    const idSet = new Set(prev.map((s) => s.id));
                    return [...prev, ...wechat.filter((s) => !idSet.has(s.id))];
                });
                setWebsiteSources((prev) => {
                    const idSet = new Set(prev.map((s) => s.id));
                    return [...prev, ...website.filter((s) => !idSet.has(s.id))];
                });
                setSearchPage(nextPage);
                setSearchHasMore(nextPage * PAGE_SIZE < res.total);
            } finally {
                setLoadingSources(false);
            }
            return;
        }

        const business_type: ChannelBusinessType = activeTab === "official_account" ? "wechat" : "website";
        if (!listHasMoreMap[business_type]) return;

        const nextPage = (listPageMap[business_type] || 1) + 1;
        setLoadingSources(true);
        try {
            const res = await listManagerSourcesApi({
                business_type,
                page: nextPage,
                page_size: PAGE_SIZE,
            });
            const mapped: InformationSource[] = (res.sources || []).map((s: ManagerSource) => ({
                id: s.id,
                name: s.name,
                avatar: s.icon,
                url: s.original_url,
                type: s.business_type === "wechat" ? "official_account" : "website",
            }));
            if (business_type === "wechat") {
                setWechatSources((prev) => {
                    const idSet = new Set(prev.map((s) => s.id));
                    return [...prev, ...mapped.filter((s) => !idSet.has(s.id))];
                });
            } else {
                setWebsiteSources((prev) => {
                    const idSet = new Set(prev.map((s) => s.id));
                    return [...prev, ...mapped.filter((s) => !idSet.has(s.id))];
                });
            }
            setListPageMap((prev) => ({ ...prev, [business_type]: nextPage }));
            setListHasMoreMap((prev) => ({
                ...prev,
                [business_type]: nextPage * PAGE_SIZE < res.total,
            }));
        } finally {
            setLoadingSources(false);
        }
    };

    // Auto-detect and process WeChat article URLs
    useEffect(() => {
        if (!expanded) return;
        if (viewMode !== "wechatProcessing") {
            processingWechatRef.current = "";
            return;
        }
        const target = searchKeyword.trim();
        if (!target || processingWechatRef.current === target) return;
        processingWechatRef.current = target;
        const token = ++wechatRequestTokenRef.current;

        const timer = setTimeout(() => {
            (async () => {
                try {
                    // Abort previous in-flight request (if any) and create a new controller for this run
                    abortWechatRequest();
                    const controller = new AbortController();
                    wechatAbortRef.current = controller;

                    const res = await addWechatSourceApi({ url: target }, { signal: controller.signal });
                    if (wechatRequestTokenRef.current !== token) return;
                    const root: any = res as any;
                    const statusCode = root?.status_code ?? root?.code;
                    if (statusCode && statusCode !== 200) {
                        setWechatAddError(true);
                        return;
                    }
                    const raw: any = root?.data ?? root ?? {};
                    const created: InformationSource = {
                        id: String(raw.id ?? raw.source_id ?? `wx-${Date.now()}`),
                        // 后端返回 name/title，否则退回为固定文案“公众号内容源”
                        name: String(raw.name ?? raw.title ?? localize("com_subscription.official_account_content_source")),
                        // 兼容后端不同字段命名，避免首次添加时头像丢失
                        avatar: raw.avatar ?? raw.icon ?? raw.source_icon,
                        url: raw.url ?? target,
                        type: "official_account"
                    };
                    setWechatSources((prev) => {
                        if (prev.some((s) => s.id === created.id)) return prev;
                        return [...prev, created];
                    });
                    setPendingSources((prev) => {
                        if (prev.length >= MAX_SOURCES) return prev;
                        if (prev.some((s) => s.id === created.id || s.url === created.url)) return prev;
                        return [...prev, created];
                    });
                } catch {
                    if (wechatRequestTokenRef.current !== token) return;
                    setWechatAddError(true);
                } finally {
                    if (wechatRequestTokenRef.current !== token) return;
                    // Clear controller for this run
                    wechatAbortRef.current = null;
                    processingWechatRef.current = "";
                }
            })();
        }, 1800);

        return () => {
            clearTimeout(timer);
            // If effect is cleaned up (keyword changes/unmount), abort request
            abortWechatRequest();
        };
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

    const handleClearSearch = () => {
        // 用户点击「暂不添加」/清空搜索：让当前公众号添加流程失效，避免异步返回后仍被加入
        wechatRequestTokenRef.current++;
        processingWechatRef.current = "";
        abortWechatRequest();
        setSearchKeyword("");
    };

    const handleConfirm = () => {
        onSourcesChange([...pendingSources]);
        onExpandChange(false);
        setSearchKeyword("");
    };

    const handleCancel = () => {
        // 用户点击「取消」关闭面板时，也要让当前公众号添加流程失效
        // 否则异步返回后仍可能把公众号加进 pendingSources
        wechatRequestTokenRef.current++;
        processingWechatRef.current = "";
        abortWechatRequest();
        onExpandChange(false);
        setSearchKeyword("");
    };

    return {
        activeTab, setActiveTab,
        searchKeyword, setSearchKeyword,
        pendingSources,
        loadingSources,
        filteredSources,
        isSearchMode,
        selectedIds,
        isAtLimit,
        viewMode,
        toggleSource,
        loadMoreSources,
        handleClearSearch,
        handleConfirm,
        handleCancel,
        wechatAddError,
        setWechatAddError,
    };
}
