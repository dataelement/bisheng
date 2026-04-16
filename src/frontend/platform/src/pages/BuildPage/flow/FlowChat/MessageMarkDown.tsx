import { AudioPlayComponent } from "@/components/voiceFunction/audioPlayButton";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { useLinsightConfig } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import Echarts from "@/workspace/markdown/Echarts";
import MermaidBlock from "@/workspace/markdown/Mermaid";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { getCitationDetail, resolveCitationDetails, type ChatCitation } from "@/controllers/API";
import CitationDocumentPreviewDrawer, { type CitationDocumentPreviewState } from "@/components/bs-comp/chatComponent/CitationDocumentPreviewDrawer";
import { CitationSourceIcon } from "@/components/bs-comp/chatComponent/CitationSourceIcon";
import {
    buildCitationPreview,
    createCitationDetailMap,
    getCitationClassName,
    getCitationSourceLabel,
    getLegacyCitationPreview,
    isRagCitation,
    transformPrivateCitations,
    type CitationDetailLoader,
    type CitationDisplayData,
    type CitationPreview,
} from "@/components/bs-comp/chatComponent/citationUtils";
import { ExternalLink, Loader2 } from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
// @ts-ignore rehype-mathjax has no local type declaration in platform.
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { visit } from "unist-util-visit";

const remarkCitationPlugin = () => {
    return (tree) => {
        visit(tree, "text", (node: any) => {
            if (typeof node.value === "string") {
                const regex = /(\[citation:(\d+)\]|\[citationref:([^\]]+)\])/g;
                if (regex.test(node.value)) {
                    node.name = "citation";
                    node.data = {
                        hName: node.name,
                        hProperties: node.attributes,
                        ...node.data,
                    };
                    return node;
                }
            }
        });
    };
};

function CitationPreviewCard({
    preview,
    detail,
    label,
    isLoading,
    error,
    onOpenDocumentPreview,
}: {
    preview: CitationPreview | null;
    detail?: ChatCitation | null;
    label?: number;
    isLoading: boolean;
    error: boolean;
    onOpenDocumentPreview?: () => void;
}) {
    if (isLoading) {
        return (
            <div className="flex min-h-[120px] w-[420px] max-w-[calc(100vw-32px)] items-center justify-center rounded-lg bg-white text-sm text-[#86909C] shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
                <Loader2 className="mr-2 size-4 animate-spin" />
                加载溯源详情...
            </div>
        );
    }

    if (error || !preview) {
        return (
            <div className="w-[420px] max-w-[calc(100vw-32px)] rounded-lg bg-white p-4 text-sm text-[#86909C] shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
                暂无溯源详情
            </div>
        );
    }

    const isWeb = preview.type === "web";

    return (
        <div className="w-[420px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg bg-white text-[#1D2129] shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
            <div className="flex items-center gap-2 border-b border-[#F2F3F5] px-4 py-3">
                <CitationSourceIcon detail={detail} preview={preview} type={preview.type} />
                {preview.type !== "web" && onOpenDocumentPreview ? (
                    <button
                        type="button"
                        onClick={onOpenDocumentPreview}
                        className="min-w-0 flex-1 truncate text-left text-[15px] font-medium leading-6 text-[#165DFF] hover:underline"
                        title={preview.title}
                    >
                        {preview.title}
                    </button>
                ) : preview.link ? (
                    <a
                        href={preview.link}
                        target="_blank"
                        rel="noreferrer"
                        className="min-w-0 flex-1 truncate text-[15px] font-medium leading-6 text-[#165DFF] hover:underline"
                    >
                        {preview.title}
                    </a>
                ) : (
                    <div className="min-w-0 flex-1 truncate text-[15px] font-medium leading-6 text-[#165DFF]">
                        {preview.title}
                    </div>
                )}
                {isWeb && <ExternalLink className="size-4 shrink-0 text-[#165DFF]" />}
            </div>
            <div className="px-4 py-3">
                <div className="border-l-2 border-[#E5E6EB] pl-3 text-[14px] leading-7 text-[#1D2129]">
                    <div className="line-clamp-4 whitespace-pre-wrap break-words">
                        {preview.snippet || "暂无内容摘要"}
                    </div>
                </div>
                <div className="mt-3 flex items-center justify-between gap-3 text-[13px] leading-5 text-[#86909C]">
                    <div className="flex min-w-0 items-center gap-2">
                        <CitationSourceIcon detail={detail} preview={preview} type={preview.type} ragIconVariant="knowledge" />
                        <span className="truncate">{preview.sourceName}</span>
                        {preview.sourceMeta && <span className="shrink-0">{preview.sourceMeta}</span>}
                    </div>
                    <div className={`shrink-0 rounded px-2 py-1 ${isWeb ? "bg-[#F3EEFF] text-[#7C3AED]" : "bg-[#EEF3FF] text-[#165DFF]"}`}>
                        [{label}] - {isWeb ? "网页" : "文档"}
                    </div>
                </div>
            </div>
        </div>
    );
}

const Citation = ({
    data,
    children,
    initialDetail,
    webContent,
    loadCitationDetail,
    onOpenDocumentPreview,
}: {
    data: Partial<CitationDisplayData>;
    children: React.ReactNode;
    initialDetail?: ChatCitation | null;
    webContent?: any;
    loadCitationDetail: CitationDetailLoader;
    onOpenDocumentPreview: (detail: ChatCitation, itemId?: string, locateChunk?: boolean) => void;
}) => {
    if (!data) return null;

    const [open, setOpen] = useState(false);
    const [detail, setDetail] = useState<ChatCitation | null>(initialDetail ?? null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(false);
    const closeTimerRef = useRef<number | null>(null);
    const citationClassName = getCitationClassName(data.type);
    const legacyPreview = data.ref?.startsWith("citation:")
        ? getLegacyCitationPreview(webContent, data.label)
        : null;
    const preview = legacyPreview ?? buildCitationPreview(detail, data);

    const fetchDetail = async () => {
        if (detail || legacyPreview || !data.citationId || data.citationId.startsWith("citation:")) {
            return detail;
        }

        setIsLoading(true);
        setError(false);
        try {
            const nextDetail = await loadCitationDetail(data.citationId);
            setDetail(nextDetail);
            return nextDetail;
        } catch (err) {
            console.error("Failed to load citation detail:", err);
            setError(true);
            return null;
        } finally {
            setIsLoading(false);
        }
    };

    const handleOpenDocumentPreview = async (event?: React.MouseEvent) => {
        event?.preventDefault();
        event?.stopPropagation();

        const nextDetail = detail ?? await fetchDetail();
        if (!nextDetail || !isRagCitation(nextDetail, data.type)) {
            return;
        }

        onOpenDocumentPreview(nextDetail, data.itemId, true);
    };

    useEffect(() => {
        if (initialDetail) {
            setDetail(initialDetail);
        }
    }, [initialDetail]);

    useEffect(() => {
        return () => {
            if (closeTimerRef.current) {
                window.clearTimeout(closeTimerRef.current);
            }
        };
    }, []);

    const handleOpenChange = (nextOpen: boolean) => {
        if (closeTimerRef.current) {
            window.clearTimeout(closeTimerRef.current);
            closeTimerRef.current = null;
        }
        setOpen(nextOpen);
        if (nextOpen) {
            void fetchDetail();
        }
    };

    const scheduleClose = () => {
        if (closeTimerRef.current) {
            window.clearTimeout(closeTimerRef.current);
        }
        closeTimerRef.current = window.setTimeout(() => {
            setOpen(false);
        }, 120);
    };

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger asChild>
                <button
                    type="button"
                    data-citation-ref={data.ref}
                    data-citation-id={data.citationId}
                    data-citation-item-id={data.itemId}
                    data-citation-type={data.type}
                    data-citation-group-key={data.groupKey}
                    data-citation-chunk-id={data.chunkId}
                    aria-label={`${getCitationSourceLabel(data.type)}引用 ${data.label ?? ""}`}
                    onClick={handleOpenDocumentPreview}
                    onMouseEnter={() => handleOpenChange(true)}
                    onMouseLeave={scheduleClose}
                    className={`ml-1 inline-flex min-h-6 min-w-6 cursor-pointer items-center justify-center rounded-xl px-2 py-0.5 text-[0.9em] font-medium leading-none transition-colors duration-200 ${citationClassName}`}
                >
                    <span>{children}</span>
                </button>
            </PopoverTrigger>
            <PopoverContent
                side="top"
                align="start"
                sideOffset={8}
                onMouseEnter={() => handleOpenChange(true)}
                onMouseLeave={scheduleClose}
                className="z-50 w-auto border-none bg-transparent p-0 shadow-none outline-none"
            >
                <CitationPreviewCard
                    preview={preview}
                    detail={detail}
                    label={data.label}
                    isLoading={isLoading}
                    error={error}
                    onOpenDocumentPreview={() => void handleOpenDocumentPreview()}
                />
            </PopoverContent>
        </Popover>
    );
};

const MessageMarkDown = React.memo(function MessageMarkDown({ message, version, chat, flowType, citations, webContent, allowRemoteCitationResolve = true }: {
    message: string;
    version?: string;
    chat?: any;
    flowType?: number;
    citations?: ChatCitation[] | null;
    webContent?: any;
    allowRemoteCitationResolve?: boolean;
}) {

    const { data: linsightConfig } = useLinsightConfig();
    const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
    function filterMermaidBlocks(input) {
        const closedMermaidPattern = /```mermaid[\s\S]*?```/g;
        const openMermaidPattern = /```mermaid[\s\S]*$/g;

        // 先删除未闭合的
        if (!closedMermaidPattern.test(input)) {
            input = input.replace(openMermaidPattern, "");
        }

        return input;
    }

    const { processedMessage, citationMap } = useMemo(() => {
        const normalizedMessage = filterMermaidBlocks(String(message || ""))
            // .replaceAll(/(\n\s{4,})/g, '\n   ') // 禁止4空格转代码
            .replaceAll(/(^\n\s{4,})/g, '\n   ') // ^只处理开头情况，否则影响代码无法缩进
            .replace(/(?<![\n\|])\n(?!\n)/g, '\n\n') // 单个换行符 处理不换行情况，例如：`Hello|There\nFriend
            .replaceAll('(bisheng/', '(/bisheng/') // TODO 临时处理方案,以后需要改为markdown插件方式处理
            .replace(/\\[\[\]]/g, '$$$$') // 处理`\[...\]`包裹的公式（四个$会被解释为两个$$）
        const { transformedContent, citationMap } = transformPrivateCitations(normalizedMessage);
        return {
            processedMessage: transformedContent,
            citationMap,
        };
    }, [message]);

    const initialCitationDetailMap = useMemo(() => createCitationDetailMap(citations), [citations]);
    const [citationDetailMap, setCitationDetailMap] = useState<Record<string, ChatCitation>>(() => initialCitationDetailMap);
    const citationDetailCacheRef = useRef<Record<string, ChatCitation>>({});
    const citationRequestCacheRef = useRef<Record<string, Promise<ChatCitation | null>>>({});
    const citationBatchRequestKeyRef = useRef<string>("");

    useEffect(() => {
        Object.entries(initialCitationDetailMap).forEach(([citationId, detail]) => {
            citationDetailCacheRef.current[citationId] = detail;
        });
        setCitationDetailMap((current) => ({
            ...current,
            ...initialCitationDetailMap,
        }));
    }, [initialCitationDetailMap]);

    useEffect(() => {
        if (!allowRemoteCitationResolve) {
            return;
        }

        const citationIds = Array.from(new Set(
            Object.values(citationMap)
                .map((item) => item.citationId)
                .filter((citationId) => citationId && !citationId.startsWith("citation:") && !citationDetailCacheRef.current[citationId]),
        ));

        if (!citationIds.length) {
            return;
        }

        const requestKey = citationIds.sort().join("|");
        if (citationBatchRequestKeyRef.current === requestKey) {
            return;
        }
        citationBatchRequestKeyRef.current = requestKey;

        void resolveCitationDetails(citationIds)
            .then((items) => {
                const nextMap: Record<string, ChatCitation> = {};
                items.forEach((detail) => {
                    if (detail?.citationId) {
                        citationDetailCacheRef.current[detail.citationId] = detail;
                        nextMap[detail.citationId] = detail;
                    }
                });
                if (Object.keys(nextMap).length) {
                    setCitationDetailMap((current) => ({
                        ...current,
                        ...nextMap,
                    }));
                }
            })
            .catch((error) => {
                console.error("Failed to resolve citation details:", error);
                citationBatchRequestKeyRef.current = "";
            });
    }, [allowRemoteCitationResolve, citationMap]);

    const loadCitationDetail = useCallback<CitationDetailLoader>(async (citationId) => {
        const cachedDetail = citationDetailCacheRef.current[citationId];
        if (cachedDetail) {
            return cachedDetail;
        }

        if (!allowRemoteCitationResolve) {
            return null;
        }

        const pendingRequest = citationRequestCacheRef.current[citationId];
        if (pendingRequest) {
            return pendingRequest;
        }

        const request = getCitationDetail(citationId)
            .then((detail) => {
                if (detail?.citationId) {
                    citationDetailCacheRef.current[detail.citationId] = detail;
                }
                citationDetailCacheRef.current[citationId] = detail;
                return detail;
            })
            .finally(() => {
                delete citationRequestCacheRef.current[citationId];
            });

        citationRequestCacheRef.current[citationId] = request;
        return request;
    }, [allowRemoteCitationResolve]);

    const handleOpenDocumentPreview = useCallback((detail: ChatCitation, itemId?: string, locateChunk = true) => {
        setDocumentPreview({
            detail,
            itemId,
            locateChunk,
        });
    }, []);

    return (
        <>
            <div className="bs-mkdown inline-block break-all max-w-full text-sm text-text-answer">
                <ReactMarkdown
                    remarkPlugins={[remarkGfm, remarkMath, remarkCitationPlugin]}
                    rehypePlugins={[rehypeMathjax]}
                    components={{
                        a: ({ node, href, children }) => {
                            return <a href={href} target="_blank" rel="noreferrer" className="text-primary underline hover:text-primary/80">{children}</a>
                        },
                        code: ({ node, className, children }) => {
                            const match = /language-(\w+)/.exec(className ?? '');
                            const lang = match && match[1];

                            if (lang === 'echarts') return <Echarts option={String(children)} />
                            if (lang === 'mermaid') return <MermaidBlock>{String(children).trim()}</MermaidBlock>

                            return <CodeBlock
                                key={Math.random()}
                                language={lang}
                                value={String(children).replace(/\n$/, "")}
                            />
                        },
                        citation: ({ children }: { children: React.ReactNode }) => {
                            if (typeof children === "string") {
                                const citationPattern = /\[citation:(\d+)\]|\[citationref:([^\]]+)\]/g;
                                const nodes: React.ReactNode[] = [];
                                let lastIndex = 0;

                                let match: RegExpExecArray | null;
                                while ((match = citationPattern.exec(children)) !== null) {
                                    const matchText = match[0];
                                    const matchIndex = match.index ?? 0;
                                    if (matchIndex > lastIndex) {
                                        nodes.push(children.slice(lastIndex, matchIndex));
                                    }

                                    const legacyIndexValue = match[1];
                                    const privateRef = match[2];

                                    if (legacyIndexValue) {
                                        const legacyIndex = Number(legacyIndexValue);
                                        if (webContent?.[legacyIndex - 1]) {
                                            nodes.push(
                                                <Citation
                                                    key={`legacy-${matchIndex}`}
                                                    webContent={webContent}
                                                    loadCitationDetail={loadCitationDetail}
                                                    onOpenDocumentPreview={handleOpenDocumentPreview}
                                                    data={{
                                                        label: legacyIndex,
                                                        ref: `citation:${legacyIndexValue}`,
                                                        type: "web",
                                                        groupKey: legacyIndexValue,
                                                        chunkId: legacyIndexValue,
                                                        citationId: `citation:${legacyIndexValue}`,
                                                        itemId: legacyIndexValue,
                                                    }}
                                                >
                                                    {legacyIndexValue}
                                                </Citation>
                                            );
                                        }
                                    } else if (privateRef) {
                                        const citationData = citationMap[privateRef];
                                        if (citationData) {
                                            nodes.push(
                                                <Citation
                                                    key={`private-${matchIndex}`}
                                                    data={citationData}
                                                    initialDetail={citationDetailMap[citationData.citationId]}
                                                    loadCitationDetail={loadCitationDetail}
                                                    onOpenDocumentPreview={handleOpenDocumentPreview}
                                                >
                                                    {citationData.label}
                                                </Citation>
                                            );
                                        }
                                    }

                                    lastIndex = matchIndex + matchText.length;
                                }

                                if (lastIndex < children.length) {
                                    nodes.push(children.slice(lastIndex));
                                }

                                return <>{nodes}</>;
                            }

                            return <>{children}</>;
                        },
                    } as any}
                >
                    {processedMessage}
                </ReactMarkdown>
                {(flowType === 1) && <div className={`text-right group-hover:opacity-100 opacity-0`}>
                    {linsightConfig?.tts_model?.id && (
                        <AudioPlayComponent
                            messageId={String()}
                            msg={processedMessage}
                        />
                    )}
                </div>}
            </div>
            <CitationDocumentPreviewDrawer
                preview={documentPreview}
                onClose={() => setDocumentPreview(null)}
            />
        </>

    );
});


export default MessageMarkDown;
