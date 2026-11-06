import { InlineCitation as SharedCitation, useCitationDetails, type InlineCitationProps } from '@bisheng/chat/citation-inline';
import { usePlatformCitationServices } from '@/components/bs-comp/chatComponent/usePlatformCitationServices';
import { CitationSourceIcon } from '@/components/bs-comp/chatComponent/CitationSourceIcon';
function Citation(props:Omit<InlineCitationProps,'citationPreviewUsesHover'>){const services=usePlatformCitationServices();return <SharedCitation key={services.scopeKey+props.data.ref} {...props} citationPreviewUsesHover presentation={{localize:services.localize,SourceIcon:CitationSourceIcon}}/>;}
import CitationDocumentPreviewDrawer, { type CitationDocumentPreviewState } from "@/components/bs-comp/chatComponent/CitationDocumentPreviewDrawer";
import { transformPrivateCitations } from "@/components/bs-comp/chatComponent/citationUtils";

import { AudioPlayComponent } from "@/components/voiceFunction/audioPlayButton";
import { type ChatCitation } from "@/controllers/API";
import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import { useWorkbenchRuntimeConfig } from "@/hooks/useWorkbenchRuntimeConfig";
import Echarts from "@/workspace/markdown/Echarts";
import MermaidBlock from "@/workspace/markdown/Mermaid";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
// @ts-ignore rehype-mathjax has no local type declaration in platform.
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { visit } from "unist-util-visit";

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

const MessageMarkDown = React.memo(function MessageMarkDown({ message, version, chat, flowType, citations, webContent, allowRemoteCitationResolve = true }: {
    message: string;
    version?: string;
    chat?: unknown;
    flowType?: number;
    citations?: ChatCitation[] | null;
    webContent?: unknown;
    allowRemoteCitationResolve?: boolean;
}) {

    const { data: linsightConfig } = useWorkbenchRuntimeConfig();
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
            .replaceAll('(bisheng/', '(/bisheng/') // TODO 临时处理方案,以后需要改为markdown插件方式处理
            .replace(/\\[\[\]]/g, '$$$$') // 处理`\[...\]`包裹的公式（四个$会被解释为两个$$）
        const { transformedContent, citationMap } = transformPrivateCitations(normalizedMessage);
        return {
            processedMessage: transformedContent,
            citationMap,
        };
    }, [message]);

    const citationServices=usePlatformCitationServices();
    useEffect(()=>{setDocumentPreview(null);},[citationServices.scopeKey]);
    const {details:citationDetailMap,forbidden:forbiddenCitationIds,expired:expiredCitationIds,load:loadCitationDetail}=useCitationDetails(citations,citationMap,citationServices,allowRemoteCitationResolve);

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
                        p: ({ children }) => <p className="mb-2 whitespace-pre-wrap">{children}</p>,
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
