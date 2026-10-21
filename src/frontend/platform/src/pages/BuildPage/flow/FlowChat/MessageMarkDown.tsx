import CitationDocumentPreviewDrawer,{ type CitationDocumentPreviewState } from "@/components/bs-comp/chatComponent/CitationDocumentPreviewDrawer";
import {
buildCitationPreview,
createCitationDetailMap,
getCitationClassName,
getCitationSourceLabel,
getLegacyCitationPreview,
isFilePreviewCitation,
isRagCitationMissingPreviewUrl,
normalizeCitationType,
transformPrivateCitations,
type CitationDetailLoader,
type CitationDisplayData
} from "@/components/bs-comp/chatComponent/citationUtils";
import { Popover,PopoverContent,PopoverTrigger } from "@/components/bs-ui/popover";
import { AudioPlayComponent } from "@/components/voiceFunction/audioPlayButton";
import { getCitationDetail,getCitationUnresolvedReason,resolveCitationDetails,type ChatCitation } from "@/controllers/API";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { useLinsightConfig } from "@/pages/ModelPage/manage/tabs/WorkbenchModel";
import Echarts from "@/workspace/markdown/Echarts";
import MermaidBlock from "@/workspace/markdown/Mermaid";

import React,{ useCallback,useEffect,useMemo,useRef,useState } from "react";
import ReactMarkdown from "react-markdown";
// @ts-ignore rehype-mathjax has no local type declaration in platform.
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { visit } from "unist-util-visit";

import { CitationPreviewCard } from "./CitationPreviewCard";

const remarkCitationPlugin = () => {
    return (tree) => {
        visit(tree, "text", (node) => {
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

const Citation = ({
    data: rawData,
    children,
    initialDetail,
    initialNotPermitted,
    initialExpired,
    webContent,
    loadCitationDetail,
    popoverKey,
    activePopoverKey,
    onActivePopoverKeyChange,
    onClosePopover,
    onOpenDocumentPreview,
}: {
    data: Partial<CitationDisplayData>;
    children: React.ReactNode;
    initialDetail?: ChatCitation | null;
    initialNotPermitted?: boolean;
    initialExpired?: boolean;
    webContent?: unknown;
    loadCitationDetail: CitationDetailLoader;
    popoverKey: string;
    activePopoverKey: string | null;
    onActivePopoverKeyChange: (key: string | null) => void;
    onClosePopover: (key: string) => void;
    onOpenDocumentPreview: (detail: ChatCitation, itemId?: string, locateChunk?: boolean) => void;
}) => {
    const data = rawData ?? ({} as Partial<CitationDisplayData>);
    const hasData = !!rawData;
    const isOpen = activePopoverKey === popoverKey;
    const [detail, setDetail] = useState<ChatCitation | null>(initialDetail ?? null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(false);
    const [notPermitted, setNotPermitted] = useState(!!initialNotPermitted);
    const [expired, setExpired] = useState(!!initialExpired);
    const closeTimerRef = useRef<number | null>(null);
    const citationClassName = getCitationClassName(data.type);
    const legacyPreview = data.ref?.startsWith("citation:")
        ? getLegacyCitationPreview(webContent, data.label)
        : null;
    const preview = legacyPreview ?? buildCitationPreview(detail, data);

    const fetchDetail = async () => {
        if (detail || notPermitted || expired || legacyPreview || !data.citationId || data.citationId.startsWith("citation:")) {
            return detail;
        }

        setIsLoading(true);
        setError(false);
        try {
            const nextDetail = await loadCitationDetail(data.citationId);
            setDetail(nextDetail);
            return nextDetail;
        } catch (err: unknown) {
            if (err && typeof err === "object" && "citationExpired" in err && err.citationExpired) {
                setExpired(true);
            } else if (err && typeof err === "object" && "citationForbidden" in err && err.citationForbidden) {
                setNotPermitted(true);
            } else {
                console.error("Failed to load citation detail:", err);
                setError(true);
            }
            return null;
        } finally {
            setIsLoading(false);
        }
    };

    const openWebCitation = (url?: string, targetWindow?: Window | null) => {
        if (!url) {
            targetWindow?.close();
            return;
        }
        if (targetWindow) {
            targetWindow.opener = null;
            targetWindow.location.href = url;
            return;
        }
        window.open(url, "_blank", "noopener,noreferrer");
    };

    const handleCitationClick = async (event?: React.MouseEvent) => {
        event?.preventDefault();
        event?.stopPropagation();

        if (notPermitted || expired) {
            handleOpenChange(!isOpen);
            return;
        }

        const isWebCitation = normalizeCitationType(preview?.type || data.type) === "web";
        if (isWebCitation && preview?.link) {
            openWebCitation(preview.link);
            return;
        }

        const pendingWebWindow = isWebCitation ? window.open("about:blank", "_blank") : null;
        const nextDetail = detail ?? await fetchDetail();
        const nextPreview = legacyPreview ?? buildCitationPreview(nextDetail, data);
        if (normalizeCitationType(nextPreview?.type || nextDetail?.type || data.type) === "web") {
            openWebCitation(nextPreview?.link, pendingWebWindow);
            return;
        }
        pendingWebWindow?.close();

        if (!nextDetail || !isFilePreviewCitation(nextDetail, data.type)) {
            return;
        }

        if (closeTimerRef.current) {
            window.clearTimeout(closeTimerRef.current);
            closeTimerRef.current = null;
        }
        onActivePopoverKeyChange(null);
        onOpenDocumentPreview(nextDetail, data.itemId, true);
    };

    useEffect(() => {
        if (initialDetail) {
            setDetail(initialDetail);
        }
    }, [initialDetail]);

    useEffect(() => {
        if (initialExpired) {
            setExpired(true);
        }
    }, [initialExpired]);

    useEffect(() => {
        if (initialNotPermitted) {
            setNotPermitted(true);
        }
    }, [initialNotPermitted]);

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
        onActivePopoverKeyChange(nextOpen ? popoverKey : null);
        if (nextOpen) {
            void fetchDetail();
        }
    };

    const scheduleClose = () => {
        if (closeTimerRef.current) {
            window.clearTimeout(closeTimerRef.current);
        }
        closeTimerRef.current = window.setTimeout(() => {
            onClosePopover(popoverKey);
        }, 120);
    };

    if (!hasData) {
        return null;
    }

    return (
        <Popover open={isOpen} onOpenChange={handleOpenChange}>
            <PopoverTrigger asChild>
                <button
                    type="button"
                    data-citation-trigger="true"
                    data-citation-ref={data.ref}
                    data-citation-id={data.citationId}
                    data-citation-item-id={data.itemId}
                    data-citation-type={data.type}
                    data-citation-group-key={data.groupKey}
                    data-citation-chunk-id={data.chunkId}
                    aria-label={`${getCitationSourceLabel(data.type)}引用 ${data.label ?? ""}`}
                    onClick={handleCitationClick}
                    onMouseEnter={() => handleOpenChange(true)}
                    onMouseLeave={scheduleClose}
                    className={`${notPermitted || expired ? "ml-2 cursor-default" : "ml-2 cursor-pointer"} inline-flex h-4 min-w-4 items-center justify-center rounded-[6px] px-1 text-[12px] font-normal leading-[18px] ${citationClassName}`}
                >
                    <span className="flex h-[18px] items-center">{children}</span>
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
                    isLoading={isLoading}
                    error={error}
                    notPermitted={notPermitted}
                    expired={expired}
                    onCardClick={() => void handleCitationClick()}
                    onOpenDocumentPreview={() => void handleCitationClick()}
                />
            </PopoverContent>
        </Popover>
    );
};

const MessageMarkDown = React.memo(function MessageMarkDown({ message, version, chat, flowType, citations, webContent, allowRemoteCitationResolve = true }: {
    message: string;
    version?: string;
    chat?: unknown;
    flowType?: number;
    citations?: ChatCitation[] | null;
    webContent?: unknown;
    allowRemoteCitationResolve?: boolean;
}) {

    const { data: linsightConfig } = useLinsightConfig();
    const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
    const [activeCitationPopoverKey, setActiveCitationPopoverKey] = useState<string | null>(null);
    const handleCloseCitationPopover = useCallback((popoverKey: string) => {
        setActiveCitationPopoverKey((currentKey) => currentKey === popoverKey ? null : currentKey);
    }, []);

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
    const citationResolvedIdsRef = useRef<Set<string>>(new Set());
    const [forbiddenCitationIds, setForbiddenCitationIds] = useState<Set<string>>(() => new Set());
    const [expiredCitationIds, setExpiredCitationIds] = useState<Set<string>>(() => new Set());

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
                .filter((citationId) => {
                    if (!citationId || citationId.startsWith("citation:")) return false;
                    if (citationResolvedIdsRef.current.has(citationId)) return false;
                    const cached = citationDetailCacheRef.current[citationId];
                    return !cached || isRagCitationMissingPreviewUrl(cached);
                }),
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
                        citationResolvedIdsRef.current.add(detail.citationId);
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
                const unresolvedIds = citationIds.filter((id) => !citationDetailCacheRef.current[id]);
                const expiredIds = unresolvedIds.filter((id) => getCitationUnresolvedReason(id) === "expired");
                const forbidden = unresolvedIds.filter((id) => getCitationUnresolvedReason(id) !== "expired");
                if (forbidden.length) {
                    setForbiddenCitationIds((prev) => {
                        const next = new Set(prev);
                        forbidden.forEach((id) => next.add(id));
                        return next;
                    });
                }
                if (expiredIds.length) {
                    setExpiredCitationIds((prev) => {
                        const next = new Set(prev);
                        expiredIds.forEach((id) => next.add(id));
                        return next;
                    });
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
                                                    popoverKey={`legacy-${matchIndex}`}
                                                    activePopoverKey={activeCitationPopoverKey}
                                                    onActivePopoverKeyChange={setActiveCitationPopoverKey}
                                                    onClosePopover={handleCloseCitationPopover}
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
                                                    initialNotPermitted={forbiddenCitationIds.has(citationData.citationId)}
                                                    initialExpired={expiredCitationIds.has(citationData.citationId)}
                                                    loadCitationDetail={loadCitationDetail}
                                                    popoverKey={`private-${matchIndex}`}
                                                    activePopoverKey={activeCitationPopoverKey}
                                                    onActivePopoverKeyChange={setActiveCitationPopoverKey}
                                                    onClosePopover={handleCloseCitationPopover}
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
                    } as import("react-markdown").Components}
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
