// src/frontend/client/src/pages/Subscription/hooks/useCrawlQueue.ts
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import pLimit from "p-limit";
import {
    addWebsiteSourceApi,
    crawlTempSourceApi,
    type InformationSource,
} from "~/api/channels";
import { generateUUID } from "~/utils";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { extractApiStatusCode } from "../errorUtils";
import { crawlErrorMessageKey, mapCrawlError, normalizeCrawlUrl, type CrawlErrorCode } from "../CreateChannel/crawlErrorUtils";

const CONCURRENCY = 3;

/** Account-level API-key crawl quota exceeded — must surface as a popup, not a queue tooltip. */
const API_KEY_LIMIT_CODE = 19006;

export type CrawlStatus = "pending" | "crawling" | "success" | "failed";

export interface CrawlPreview {
    name: string;
    icon?: string;
    articles?: { title: string; url: string }[];
}

export interface CrawlQueueItem {
    id: string;
    url: string;
    status: CrawlStatus;
    sourceId?: string;
    sourceName?: string;
    sourceIcon?: string;
    preview?: CrawlPreview;
    errorCode?: CrawlErrorCode;
    abortController: AbortController;
}

export interface UseCrawlQueueOptions {
    onSourceAdded: (source: InformationSource) => void;
}

export interface UseCrawlQueueReturn {
    queue: CrawlQueueItem[];
    inProgressCount: number;
    hasItems: boolean;
    panelOpen: boolean;
    setPanelOpen: (v: boolean) => void;
    enqueue: (url: string) => void;
    abort: (id: string) => void;
    clear: () => void;
}

function looksLikeSinglePage(url: string, raw: any): boolean {
    if (raw?.single_page === true) return true;
    const lower = url.toLowerCase();
    if (/(list|index|column|columns|catalog|category|news)/.test(lower)) return false;
    return /(article|detail|content|zhengce|policy|post)/.test(lower);
}

export function useCrawlQueue({ onSourceAdded }: UseCrawlQueueOptions): UseCrawlQueueReturn {
    const [queue, setQueue] = useState<CrawlQueueItem[]>([]);
    const [panelOpen, setPanelOpen] = useState(false);
    const limitRef = useRef(pLimit(CONCURRENCY));
    const mountedRef = useRef(true);
    const onSourceAddedRef = useRef(onSourceAdded);
    onSourceAddedRef.current = onSourceAdded;

    const localize = useLocalize();
    const { showToast } = useToastContext();
    const showToastRef = useRef(showToast);
    showToastRef.current = showToast;
    const localizeRef = useRef(localize);
    localizeRef.current = localize;

    // 19006 is an account-level quota error: every further crawl also fails, so
    // Also surface it as an error toast while keeping the queue reason visible.
    const notifyIfLimitExceeded = useCallback((errorCode: CrawlErrorCode) => {
        if (errorCode !== API_KEY_LIMIT_CODE) return;
        showToastRef.current?.({
            message: localizeRef.current(crawlErrorMessageKey(API_KEY_LIMIT_CODE)),
            severity: NotificationSeverity.WARNING,
        });
    }, []);

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);

    const inProgressCount = useMemo(
        () => queue.filter(it => it.status === "pending" || it.status === "crawling").length,
        [queue]
    );

    const prevInProgressRef = useRef(0);
    useEffect(() => {
        const prev = prevInProgressRef.current;
        if (prev === 0 && inProgressCount > 0) setPanelOpen(true);
        else if (prev > 0 && inProgressCount === 0) {
            setPanelOpen(queue.some(item => item.status === "failed"));
        }
        prevInProgressRef.current = inProgressCount;
    }, [inProgressCount, queue]);

    const updateItem = useCallback((id: string, patch: Partial<CrawlQueueItem>) => {
        if (!mountedRef.current) return;
        setQueue(prev => {
            const idx = prev.findIndex(it => it.id === id);
            if (idx === -1) return prev;
            const next = prev.slice();
            next[idx] = { ...next[idx], ...patch };
            return next;
        });
    }, []);

    const runWorker = useCallback(async (item: CrawlQueueItem) => {
        const { id, abortController } = item;
        const url = normalizeCrawlUrl(item.url) ?? item.url;
        const signal = abortController.signal;
        if (signal.aborted) return;
        updateItem(id, { status: "crawling" });

        let preview: CrawlPreview | undefined;
        try {
            const res = await crawlTempSourceApi({ url }, { signal, showError: false });
            const root: any = res ?? {};
            const codeRaw = extractApiStatusCode(res);
            if (codeRaw != null && codeRaw !== 200 && codeRaw !== 0) {
                const errorCode = mapCrawlError(res);
                notifyIfLimitExceeded(errorCode);
                updateItem(id, { status: "failed", errorCode });
                return;
            }
            const raw: any = root.data ?? root;
            if (looksLikeSinglePage(url, raw)) {
                updateItem(id, { status: "failed", errorCode: 19005 });
                return;
            }
            let name = raw.name as string | undefined;
            if (!name) {
                try {
                    name = new URL(url).hostname.replace(/^www\./, "");
                } catch {
                    name = url.replace(/^https?:\/\//, "").split("/")[0] || url;
                }
            }
            const articles: { title: string; url: string }[] =
                ((raw.article_links as any[] | undefined) ?? []).slice(0, 20).map(link => ({
                    title: String(link.title ?? ""),
                    url: String(link.url ?? url),
                }));
            preview = { name: name || url, icon: raw.icon, articles };
        } catch (error) {
            if (signal.aborted || (error as any)?.name === "AbortError") return;
            const errorCode = mapCrawlError(error);
            notifyIfLimitExceeded(errorCode);
            updateItem(id, { status: "failed", errorCode });
            return;
        }

        if (signal.aborted) return;

        try {
            const addRes = await addWebsiteSourceApi({ url }, { signal, showError: false });
            const code = extractApiStatusCode(addRes);
            if (code != null && code !== 200) {
                const errorCode = mapCrawlError(addRes);
                notifyIfLimitExceeded(errorCode);
                updateItem(id, { status: "failed", errorCode });
                return;
            }
            const raw: any = (addRes as any)?.data ?? addRes ?? {};
            const source: InformationSource = {
                id: String(raw.id ?? raw.source_id ?? `web-${Date.now()}`),
                name: String(raw.name ?? raw.title ?? preview?.name ?? url),
                type: "website",
                url: raw.url ?? url,
                avatar: raw.icon ?? raw.avatar ?? preview?.icon,
            };
            updateItem(id, {
                status: "success",
                sourceId: source.id,
                sourceName: source.name,
                sourceIcon: source.avatar,
                preview,
            });
            if (mountedRef.current) onSourceAddedRef.current(source);
        } catch (error) {
            if (signal.aborted || (error as any)?.name === "AbortError") return;
            const errorCode = mapCrawlError(error);
            notifyIfLimitExceeded(errorCode);
            updateItem(id, { status: "failed", errorCode });
        }
    }, [updateItem, notifyIfLimitExceeded]);

    const enqueue = useCallback((url: string) => {
        const normalizedUrl = normalizeCrawlUrl(url);
        const id = generateUUID(8);
        const abortController = new AbortController();
        const item: CrawlQueueItem = {
            id,
            url: url.trim(),
            status: normalizedUrl ? "pending" : "failed",
            ...(normalizedUrl ? {} : { errorCode: "invalid_url" as const }),
            abortController,
        };
        setQueue(prev => [...prev, item]);
        setPanelOpen(true);
        if (normalizedUrl === null) return;
        limitRef.current(() => runWorker(item)).catch(() => { /* swallow */ });
    }, [runWorker]);

    const abort = useCallback((id: string) => {
        setQueue(prev => {
            const item = prev.find(it => it.id === id);
            if (item) item.abortController.abort();
            return prev.filter(it => it.id !== id);
        });
    }, []);

    const clear = useCallback(() => {
        setQueue(prev => {
            for (const it of prev) it.abortController.abort();
            return [];
        });
        setPanelOpen(false);
        prevInProgressRef.current = 0;
    }, []);

    useEffect(() => () => clear(), [clear]);

    return {
        queue,
        inProgressCount,
        hasItems: queue.length > 0,
        panelOpen,
        setPanelOpen,
        enqueue,
        abort,
        clear,
    };
}
