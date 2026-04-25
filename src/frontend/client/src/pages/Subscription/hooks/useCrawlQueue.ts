// src/frontend/client/src/pages/Subscription/hooks/useCrawlQueue.ts
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import pLimit from "p-limit";
import {
    addWebsiteSourceApi,
    crawlTempSourceApi,
    type InformationSource,
} from "~/api/channels";
import { generateUUID } from "~/utils";
import { extractApiStatusCode } from "../errorUtils";

const CONCURRENCY = 3;

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
    errorCode?: number;
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

function mapCrawlError(error: unknown): number {
    const code = extractApiStatusCode(error);
    if (code === 19006 || code === 19005 || code === 19004 || code === 19003) return code;
    if (code === 13005) return 19005;
    if (code === 13004) return 19004;
    if (code === 13003) return 19003;
    return 19003;
}

export function useCrawlQueue({ onSourceAdded }: UseCrawlQueueOptions): UseCrawlQueueReturn {
    const [queue, setQueue] = useState<CrawlQueueItem[]>([]);
    const [panelOpen, setPanelOpen] = useState(false);
    const limitRef = useRef(pLimit(CONCURRENCY));
    const mountedRef = useRef(true);
    const onSourceAddedRef = useRef(onSourceAdded);
    onSourceAddedRef.current = onSourceAdded;

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
        else if (prev > 0 && inProgressCount === 0) setPanelOpen(false);
        prevInProgressRef.current = inProgressCount;
    }, [inProgressCount]);

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
        const { id, url, abortController } = item;
        const signal = abortController.signal;
        if (signal.aborted) return;
        updateItem(id, { status: "crawling" });

        let preview: CrawlPreview | undefined;
        try {
            const res = await crawlTempSourceApi({ url }, { signal, showError: false });
            const root: any = res ?? {};
            const codeRaw = root?.status_code ?? root?.code;
            if (codeRaw && codeRaw !== 200) {
                const code = Number(codeRaw);
                updateItem(id, {
                    status: "failed",
                    errorCode: [19003, 19004, 19005, 19006].includes(code) ? code : 19003,
                });
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
                ((raw.article_links as any[] | undefined) ?? []).slice(0, 20).map(item => ({
                    title: String(item.title ?? ""),
                    url: String(item.url ?? url),
                }));
            preview = { name: name || url, icon: raw.icon, articles };
        } catch (error) {
            if (signal.aborted || (error as any)?.name === "AbortError") return;
            updateItem(id, { status: "failed", errorCode: mapCrawlError(error) });
            return;
        }

        if (signal.aborted) return;

        try {
            const addRes = await addWebsiteSourceApi({ url }, { signal, showError: false });
            const code = extractApiStatusCode(addRes);
            if (code != null && code !== 200) {
                updateItem(id, { status: "failed", errorCode: 19003 });
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
            updateItem(id, { status: "failed", errorCode: 19003 });
        }
    }, [updateItem]);

    const enqueue = useCallback((url: string) => {
        const id = generateUUID(8);
        const abortController = new AbortController();
        const item: CrawlQueueItem = {
            id,
            url,
            status: "pending",
            abortController,
        };
        setQueue(prev => [...prev, item]);
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
