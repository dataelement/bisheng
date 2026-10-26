import { InlineCitation as Citation } from './InlineCitation';
import { useCitationDetails } from '@bisheng/chat/citation-inline';
import { useClientCitationServices } from './useClientCitationServices';
import { code } from './LegacyMarkdownCode';
import { CompactMarkdownImage, MarkdownImage } from './LegacyMarkdownImages';
export {codeNoExecution,code} from './LegacyMarkdownCode';
import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';

import ReactMarkdown from 'react-markdown';
import { useRecoilValue } from 'recoil';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import rehypeSlug from 'rehype-slug';
import remarkDirective from 'remark-directive';
import remarkGfm from 'remark-gfm';
import { rehypeBr } from '~/utils/rehypeBr';
import remarkMath from 'remark-math';
import supersub from 'remark-supersub';
import type { Pluggable } from 'unified';
import { ArtifactProvider, CodeBlockProvider, useToastContext } from '~/Providers';
import { Artifact, artifactPlugin } from '~/components/Artifacts/Artifact';
import { remarkCitationPlugin } from '~/components/Artifacts/remarkCitationPlugin';

import { useFileDownload } from '~/hooks/queries/data-provider';

import useLocalize from '~/hooks/useLocalize';
import useMediaQuery from '~/hooks/useMediaQuery';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import store from '~/store';
import { langSubset, preprocessLaTeX } from '~/utils';
import { type ChatCitation } from '~/api/chatApi';
import { transformPrivateCitations, type CitationDisplayData } from './citationUtils';
import type { CitationReferencesDesktopPayload } from './CitationReferencesDrawer';
import CitationDocumentPreviewDrawer, { type CitationDocumentPreviewState } from './CitationDocumentPreviewDrawer';
import { isDeliverableLinkHref } from '~/components/Linsight/Artifacts/artifactUtils';

type TAnchorProps = {
  href: string;
  children: React.ReactNode;
};

export const a: React.ElementType = memo(({ href, children }: TAnchorProps) => {
  const user = useRecoilValue(store.user);
  const { showToast } = useToastContext();
  const localize = useLocalize();

  const {
    file_id = '',
    filename = '',
    filepath,
  } = useMemo(() => {
    const pattern = new RegExp(`(?:files|outputs)/${user?.id}/([^\\s]+)`);
    const match = href.match(pattern);
    if (match && match[0]) {
      const path = match[0];
      const parts = path.split('/');
      const name = parts.pop();
      const file_id = parts.pop();
      return { file_id, filename: name, filepath: path };
    }
    return { file_id: '', filename: '', filepath: '' };
  }, [user?.id, href]);

  const { refetch: downloadFile } = useFileDownload(user?.id ?? '', file_id);
  const props: { target?: string; onClick?: React.MouseEventHandler } = { target: '_new' };

  // In-page anchor (e.g. a generated table-of-contents `#heading`, or a gfm
  // footnote ref). The default `target="_new"` would spawn a blank tab; instead
  // scroll the matching element into view within the current markdown panel.
  if (href?.startsWith('#')) {
    const handleAnchorClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
      event.preventDefault();
      const raw = href.slice(1);
      // href may arrive percent-encoded or as raw CJK; tolerate malformed `%`.
      let id = raw;
      try {
        id = decodeURIComponent(raw);
      } catch {
        id = raw;
      }
      if (!id) {
        return;
      }
      const scope = event.currentTarget.closest('.bs-mkdown') ?? document;
      const target =
        (scope.querySelector(`[id="${CSS.escape(id)}"]`) as HTMLElement | null) ??
        document.getElementById(id);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    return (
      <a href={href} onClick={handleAnchorClick}>
        {children}
      </a>
    );
  }

  if (!file_id || !filename) {
    return (
      <a href={href} {...props}>
        {children}
      </a>
    );
  }

  const handleDownload = async (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    try {
      const stream = await downloadFile();
      if (stream.data == null || stream.data === '') {
        console.error('Error downloading file: No data found');
        showToast({
          status: 'warning',
          message: localize('com_ui_download_error'),
        });
        return;
      }
      const link = document.createElement('a');
      link.href = stream.data;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(stream.data);
    } catch (error) {
      console.error('Error downloading file:', error);
    }
  };

  props.onClick = handleDownload;
  props.target = '_blank';

  return (
    <a
      href={filepath.startsWith('files/') ? `/api/${filepath}` : `/api/files/${filepath}`}
      {...props}
    >
      {children}
    </a>
  );
});

type ArtifactLinkResolver = (href: string) => unknown | undefined;

type ArtifactLinkAnchorProps = TAnchorProps & {
  resolveArtifactLink: ArtifactLinkResolver;
  onArtifactPreview: (file: unknown) => void;
};

/** Linsight deliverable preview: map markdown file links to workspace artifacts. */
const ArtifactLinkAnchor = memo(({
  href,
  children,
  resolveArtifactLink,
  onArtifactPreview,
}: ArtifactLinkAnchorProps) => {
  const localize = useLocalize();
  const matched = useMemo(() => resolveArtifactLink(href), [href, resolveArtifactLink]);
  const isPhantom = !matched && typeof href === 'string' && isDeliverableLinkHref(href);
  // Once per link rather than per render (the component is memo'd but still
  // re-renders with its parent): support needs to tell "the model claimed a file
  // it never wrote" from "our resolver failed to match a real one".
  useEffect(() => {
    if (isPhantom) {
      console.warn('[Linsight] deliverable link matches no artifact of this run:', href);
    }
  }, [isPhantom, href]);

  if (matched) {
    return (
      <button
        type="button"
        className="text-blue-600 underline transition-colors hover:text-blue-700"
        onClick={() => onArtifactPreview(matched)}
      >
        {children}
      </button>
    );
  }
  // The model named a deliverable this run never produced. Don't navigate (the
  // relative output/ path is not a route), and don't keep it blue either — a blue
  // span that does nothing reads as a broken app rather than as a model that
  // overstated itself. Muted + an explicit badge, the same treatment an
  // unresolvable image ref gets below.
  if (isPhantom) {
    return (
      <span className="text-gray-400" title={localize('com_linsight_deliverable_not_generated_hint')}>
        {children}
        <span className="ml-1 text-xs">{localize('com_linsight_deliverable_not_generated')}</span>
      </span>
    );
  }
  return React.createElement(a, { href, children });
});

type TParagraphProps = {
  children: React.ReactNode;
};

export const p: React.ElementType = memo(({ children }: TParagraphProps) => {
  return <p className="mb-2 whitespace-pre-wrap">{children}</p>;
});

const cursor = ' ';

type TContentProps = {
  content: string;
  showCursor?: boolean;
  isLatestMessage: boolean;
  citations?: ChatCitation[] | null;
  messageId?: string;
  onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
};

const Markdown = memo(({
  content = '',
  showCursor,
  isLatestMessage,
  webContent,
  citations,
  messageId,
  onOpenCitationPanel,
  resolveImageSrc,
  resolveArtifactLink,
  onArtifactPreview,
  compactImages = false,
  onOpenSourcePreview,
}: TContentProps & {
  webContent: any;
  /**
   * Box inline images (320px high, 60% / 480px wide) with click-to-enlarge.
   * On for the knowledge-space and subscription assistants; daily chat keeps
   * the default <img>. Ignored when `resolveImageSrc` is set.
   */
  compactImages?: boolean;
  /**
   * Optional async resolver for relative image refs inside the markdown. When
   * provided, a custom <img> renderer resolves `![](charts/x.png)` to a real URL
   * (Linsight artifact preview); when absent, images fall back to react-markdown's
   * default <img> (chat bubbles — unchanged).
   */
  resolveImageSrc?: (src: string) => Promise<string | null>;
  /** Map markdown file links (e.g. output/report.md) to a workspace artifact. */
  resolveArtifactLink?: ArtifactLinkResolver;
  /** Open the matched artifact in the Linsight preview panel. */
  onArtifactPreview?: (file: unknown) => void;
  /**
   * F074: hand a cited document to the host instead of the floating drawer —
   * the task-mode workspace shows it beside the report, on every screen width.
   */
  onOpenSourcePreview?: (preview: CitationDocumentPreviewState) => void;
}) => {
  const LaTeXParsing = useRecoilValue<boolean>(store.LaTeXParsing);
  const isMobileLayout = usePrefersMobileLayout();
  /**
   * 可精确指向且具备 hover 时用悬停打开溯源卡片、点击角标进全文；否则（触控为主）用点击切换卡片。
   * 不按视口宽度区分，避免 PC 小窗或分屏宽度不足 1024px 时被误判为触控交互。
   */
  const citationPreviewUsesHover = useMediaQuery(
    '(hover: hover) and (pointer: fine)',
  );
  const isInitializing = content === '';
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

  const { currentContent, citationMap } = useMemo(() => {
    if (isInitializing) {
      return { currentContent: '', citationMap: {} as Record<string, CitationDisplayData> };
    }
    const message = LaTeXParsing ? preprocessLaTeX(content) : content;
    //         return `\`\`\`mermaid
    //             graph TD
    //               A[Next.js] --> B[Markdoc]
    //               B --> C[Mermaid Node]
    //               C --> D[渲染流程图]
    //               D --> E{交互式图表}
    // \`\`\``;
    //     return `\`\`\`echarts
    //     {"xAxis":{"type":"category","data":["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]},"yAxis":{"type":"value"},"series":[{"data":[120,200,150,80,70,110,130],"type":"bar"}]}
    // \`\`\``
    const normalizedContent = filterMermaidBlocks(message);
    const { transformedContent, citationMap } = transformPrivateCitations(normalizedContent);

    return {
      currentContent: transformedContent,
      citationMap,
    };
    // .replaceAll('(bisheng/', '(/bisheng/') // TODO 临时处理方案,以后需要改为markdown插件方式处理
    // .replace(/\\[\[\]]/g, '$$') // 处理`\[...\]`包裹的公式
  }, [content, LaTeXParsing, isInitializing]);

  const rehypePlugins = useMemo(
    () => [
      // Add stable `id`s to headings so generated table-of-contents `#anchor`
      // links have a target to scroll to (github-slugger convention matches the
      // anchors LLMs emit).
      rehypeSlug,
      // Turn literal <br> into real line breaks (e.g. inside table cells).
      rehypeBr,
      [rehypeKatex, { output: 'mathml' }],
      [
        rehypeHighlight,
        {
          detect: true,
          ignoreMissing: true,
          subset: langSubset,
        },
      ],
    ],
    [],
  );

  const remarkPlugins: Pluggable[] = useMemo(
    () => [
      supersub,
      remarkGfm,
      remarkDirective,
      artifactPlugin,
      [remarkMath, { singleDollarTextMath: true }],
      remarkCitationPlugin
    ],
    [],
  );

  const citationServices=useClientCitationServices();
    useEffect(()=>{setDocumentPreview(null);},[citationServices.scopeKey]);
  const {details:citationDetailMap,forbidden:forbiddenCitationIds,expired:expiredCitationIds,load:loadCitationDetail}=useCitationDetails(citations,citationMap,citationServices);

  const handleOpenDocumentPreview = useCallback((detail: ChatCitation, itemId?: string, locateChunk = true) => {
    const nextPreview = {
      detail,
      itemId,
      locateChunk,
    };

    if (onOpenSourcePreview) {
      onOpenSourcePreview(nextPreview);
      return;
    }

    if (!isMobileLayout && onOpenCitationPanel) {
      onOpenCitationPanel({
        messageId,
        content,
        webContent,
        citations,
        referenceItems: [],
        initialDocumentPreview: nextPreview,
      });
      return;
    }

    setDocumentPreview({
      detail,
      itemId,
      locateChunk,
    });
  }, [citations, content, isMobileLayout, messageId, onOpenCitationPanel, onOpenSourcePreview, webContent]);

  useEffect(() => {
    if (!documentPreview || isMobileLayout || !onOpenCitationPanel) {
      return;
    }

    onOpenCitationPanel({
      messageId,
      content,
      webContent,
      citations,
      referenceItems: [],
      initialDocumentPreview: documentPreview,
    });
    setDocumentPreview(null);
  }, [citations, content, documentPreview, isMobileLayout, messageId, onOpenCitationPanel, webContent]);

  // Cursor
  if (isInitializing) {
    return (
      <div className="absolute top-10">
        <p className="relative">
          <span className={isLatestMessage ? 'result-thinking' : ''} />
        </p>
      </div>
    );
  }

  // The same chunk ref is reused across markers, and matchIndex is only unique
  // within a single text node — so two markers can collide on the same
  // popoverKey. A render-scoped sequence guarantees a globally-unique key per
  // marker (the single activeCitationPopoverKey can then track each one).
  let citationKeySeq = 0;

  return (
    <ArtifactProvider>
      <CodeBlockProvider>
        <ReactMarkdown
          /** @ts-ignore */
          remarkPlugins={remarkPlugins}
          /* @ts-ignore */
          rehypePlugins={rehypePlugins}
          components={
            {
              code,
              a: resolveArtifactLink && onArtifactPreview
                ? ({ href, children }: TAnchorProps) => (
                    <ArtifactLinkAnchor
                      href={href}
                      resolveArtifactLink={resolveArtifactLink}
                      onArtifactPreview={onArtifactPreview}
                    >
                      {children}
                    </ArtifactLinkAnchor>
                  )
                : a,
              p,
              artifact: Artifact,
              // Resolve relative image refs (Linsight deliverable preview) only when
              // a resolver is injected; chat bubbles keep the default <img>.
              ...(resolveImageSrc
                ? {
                    img: ({ src, alt, title }: { src?: string; alt?: string; title?: string }) => (
                      <MarkdownImage src={src} alt={alt} title={title} resolveImageSrc={resolveImageSrc} />
                    ),
                  }
                : compactImages
                  ? { img: CompactMarkdownImage }
                  : {}),
              citation: ({ children }: { children: React.ReactNode }) => {
                if (typeof children === 'string') {
                  const citationPattern = /\[citation:(\d+)\]|\[citationref:([^\]]+)\]/g;
                  const nodes: React.ReactNode[] = [];
                  let lastIndex = 0;

                  for (const match of children.matchAll(citationPattern)) {
                    const matchText = match[0];
                    const matchIndex = match.index ?? 0;
                    const citationKeyId = citationKeySeq++;

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
                            key={`legacy-${legacyIndexValue}-${matchIndex}-${citationKeyId}`}
                            webContent={webContent}
                            loadCitationDetail={loadCitationDetail}
                            popoverKey={`legacy-${legacyIndexValue}-${matchIndex}-${citationKeyId}`}
                            activePopoverKey={activeCitationPopoverKey}
                            onActivePopoverKeyChange={setActiveCitationPopoverKey}
                            onClosePopover={handleCloseCitationPopover}
                            onOpenDocumentPreview={handleOpenDocumentPreview}
                            citationPreviewUsesHover={citationPreviewUsesHover}
                            data={{
                              label: legacyIndex,
                              ref: `citation:${legacyIndexValue}`,
                              type: 'web',
                              groupKey: legacyIndexValue,
                              chunkId: legacyIndexValue,
                              citationId: `citation:${legacyIndexValue}`,
                              itemId: legacyIndexValue,
                            }}
                          >
                            {legacyIndexValue}
                          </Citation>
                        );
                      } else {
                        const citationDetail = citations?.[legacyIndex - 1] ?? null;
                        const citationData = citationDetail
                          ? {
                            label: legacyIndex,
                            ref: `citation:${legacyIndexValue}`,
                            type: citationDetail.type || 'knowledgeSearch',
                            groupKey: citationDetail.citationId,
                            chunkId: String(citationDetail.itemId || citationDetail.sourcePayload?.items?.[0]?.itemId || legacyIndexValue),
                            citationId: citationDetail.citationId,
                            itemId: String(citationDetail.itemId || citationDetail.sourcePayload?.items?.[0]?.itemId || legacyIndexValue),
                          }
                          : null;
                        if (citationData) {
                          nodes.push(
                            <Citation
                              key={`rag-legacy-${citationData.ref}-${matchIndex}-${citationKeyId}`}
                              data={citationData}
                              initialDetail={citationDetailMap[citationData.citationId] ?? citationDetail}
                              initialNotPermitted={forbiddenCitationIds.has(citationData.citationId)}
                              initialExpired={expiredCitationIds.has(citationData.citationId)}
                              loadCitationDetail={loadCitationDetail}
                              popoverKey={`rag-legacy-${citationData.ref}-${matchIndex}-${citationKeyId}`}
                              activePopoverKey={activeCitationPopoverKey}
                              onActivePopoverKeyChange={setActiveCitationPopoverKey}
                              onClosePopover={handleCloseCitationPopover}
                              onOpenDocumentPreview={handleOpenDocumentPreview}
                              citationPreviewUsesHover={citationPreviewUsesHover}
                            >
                              {legacyIndexValue}
                            </Citation>
                          );
                        }
                      }
                    } else if (privateRef) {
                      const citationData = citationMap[privateRef];
                      if (citationData) {
                        nodes.push(
                          <Citation
                            key={`private-${privateRef}-${matchIndex}-${citationKeyId}`}
                            data={citationData}
                            initialDetail={citationDetailMap[citationData.citationId]}
                            initialNotPermitted={forbiddenCitationIds.has(citationData.citationId)}
                              initialExpired={expiredCitationIds.has(citationData.citationId)}
                            loadCitationDetail={loadCitationDetail}
                            popoverKey={`private-${privateRef}-${matchIndex}-${citationKeyId}`}
                            activePopoverKey={activeCitationPopoverKey}
                            onActivePopoverKeyChange={setActiveCitationPopoverKey}
                            onClosePopover={handleCloseCitationPopover}
                            onOpenDocumentPreview={handleOpenDocumentPreview}
                            citationPreviewUsesHover={citationPreviewUsesHover}
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

                  return (
                    <>
                      {nodes}
                    </>
                  );
                }

                return <>{children}</>;
              }
            } as {
              [nodeType: string]: React.ElementType;
            }
          }
        >
          {isLatestMessage && (showCursor ?? false) ? currentContent + cursor : currentContent}
        </ReactMarkdown>
        <CitationDocumentPreviewDrawer
          preview={documentPreview}
          onClose={() => setDocumentPreview(null)}
        />
      </CodeBlockProvider>
    </ArtifactProvider>
  );
});

export default Markdown;
