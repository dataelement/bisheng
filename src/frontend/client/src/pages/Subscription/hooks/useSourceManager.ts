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
    const prevExpanded = useRef(false);
    const processingWechatRef = useRef("");
    const localize = useLocalize();

    // Sync pending sources when panel opens
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

    // Load source list from API
    useEffect(() => {
        if (!expanded) return;
        if (searchKeyword.trim()) return; 
        const load = async (business_type: ChannelBusinessType) => {
            setLoadingSources(true);
            try {
                const res = await listManagerSourcesApi({ business_type, page: 1, page_size: 20 });
                const mapped: InformationSource[] = (res.sources || []).map((s: ManagerSource) => ({
                    id: s.id,
                    name: s.name,
                    avatar: s.icon,
                    url: s.original_url,
                    type: s.business_type === "wechat" ? "official_account" : "website"
                }));
                if (business_type === "wechat") setWechatSources(mapped);
                else setWebsiteSources(mapped);
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
            } catch {
                // 出错时保持现有列表
            } finally {
                setLoadingSources(false);
            }
        };

        load();
    }, [expanded, searchKeyword]);

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

        const timer = setTimeout(() => {
            (async () => {
                try {
                    const res = await addWechatSourceApi({ url: target });
                    const raw: any = (res as any)?.data ?? res ?? {};
                    const created: InformationSource = {
                        id: String(raw.id ?? raw.source_id ?? `wx-${Date.now()}`),
                        // 后端返回 name/title，否则退回为固定文案“公众号内容源”
                        name: String(raw.name ?? raw.title ?? "公众号内容源"),
                        avatar: raw.avatar,
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
                    // Fallback to local add on failure
                    setPendingSources((prev) => {
                        if (prev.length >= MAX_SOURCES) return prev;
                        if (prev.some((s) => s.url === target)) return prev;
                        return [
                            ...prev,
                            {
                                id: `wx-${Date.now()}`,
                                name: "公众号内容源",
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
        handleClearSearch,
        handleConfirm,
        handleCancel,
    };
}
