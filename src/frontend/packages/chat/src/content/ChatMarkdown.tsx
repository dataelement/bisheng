import '../styles/index.css';
import { CLIENT_MARKDOWN_DEFAULTS } from './markdownConfig';
import { useMarkdownViewport } from './useMarkdownViewport';
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components, type ExtraProps } from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import rehypeSlug from 'rehype-slug';
import remarkDirective from 'remark-directive';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import supersub from 'remark-supersub';
import type { Pluggable, Plugin } from 'unified';
import { preprocessLaTeX } from './latex';
import { langSubset } from './languages';
import { artifactPlugin, rehypeBr, remarkCitationPlugin } from './plugins';
import { transformPrivateCitations } from './citationMarkers';
import { MarkdownServicesContext, useMarkdownServices } from './MarkdownServices';
import { CitationText } from './CitationText';
import { MarkdownCode } from './MarkdownCode';
import { useCitationDetails } from './useCitationDetails';
import type { ChatCitation, ChatCitationPayload, CitationDocumentPreviewState, CitationReferencesDesktopPayload, MarkdownServices } from './types';

export interface ChatMarkdownProps {
  content: string;
  services: MarkdownServices;
  webContent?: ChatCitationPayload[];
  citations?: ChatCitation[] | null;
  messageId?: string;
  onOpenCitationPanel?: (payload: CitationReferencesDesktopPayload) => void;
}
function MarkdownLink({ href = '', children }: { href?: string; children?: ReactNode }) {
  const services = useMarkdownServices();
  return <a href={href} target={href.startsWith('#') ? undefined : '_blank'} rel="noopener noreferrer" onClick={event => {
    if (href.startsWith('#')) {
      event.preventDefault(); let id = href.slice(1);
      try { id = decodeURIComponent(id); } catch { /* Keep malformed encoded anchors readable. */ }
      const scope = event.currentTarget.closest('.bs-mkdown') ?? document;
      const target = scope.querySelector(`[id="${CSS.escape(id)}"]`) ?? document.getElementById(id);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    void services.onLinkClick?.(href, event);
  }}>{children}</a>;
}
function ChatMarkdownContent({ content, webContent, citations, messageId, onOpenCitationPanel }: Omit<ChatMarkdownProps, 'services'>) {
  const services = useMarkdownServices();
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
  const { transformedContent, citationMap } = useMemo(() => {
    let value = services.latexParsing === false ? content : preprocessLaTeX(content);
    if (!/```mermaid[\s\S]*?```/.test(value)) value = value.replace(/```mermaid[\s\S]*$/, '');
    return transformPrivateCitations(value);
  }, [content, services.latexParsing]);
  const { details, forbidden, expired, load } = useCitationDetails(citations, citationMap);
  const handleOpen = useCallback((detail: ChatCitation, itemId?: string, locateChunk = true) => {
    const next = { detail, itemId, locateChunk };
    if (!services.isMobileLayout && onOpenCitationPanel) {
      onOpenCitationPanel({ messageId, content, webContent, citations, referenceItems: [], initialDocumentPreview: next });
    } else setDocumentPreview(next);
  }, [citations, content, messageId, onOpenCitationPanel, services.isMobileLayout, webContent]);
  const handleClose = useCallback((key: string) => setActiveKey(current => current === key ? null : current), []);
  const remarkPlugins: Pluggable[] = [supersub, remarkGfm, remarkDirective, artifactPlugin, [remarkMath, { singleDollarTextMath: CLIENT_MARKDOWN_DEFAULTS.singleDollarTextMath }], remarkCitationPlugin];
  // These existing client plugins use older unified typings; their runtime contract is unchanged.
  const rehypePlugins: Pluggable[] = [rehypeSlug, rehypeBr, [rehypeKatex as unknown as Plugin, { output: CLIENT_MARKDOWN_DEFAULTS.mathOutput }], [rehypeHighlight as unknown as Plugin, { detect: CLIENT_MARKDOWN_DEFAULTS.highlightDetect, ignoreMissing: CLIENT_MARKDOWN_DEFAULTS.highlightIgnoreMissing, subset: langSubset }]];
  let citationSequence = 0;
  const components: Components & Record<string, React.ElementType> = {
    code: MarkdownCode,
    pre: ({ children }) => <>{children}</>,
    a: MarkdownLink,
    p: ({ children }) => <p className="mb-2 whitespace-pre-wrap">{children}</p>,
    artifact: props => <>{services.renderArtifact?.(props)}</>,
    citation: ({ children, node }: { children?: ReactNode } & ExtraProps) => <CitationText scope={String(node?.position?.start.offset ?? citationSequence++)} webContent={webContent} citations={citations} citationMap={citationMap}
      details={details} forbidden={forbidden} expired={expired} load={load} activeKey={activeKey} onActiveKeyChange={setActiveKey}
      onClose={handleClose} onOpen={handleOpen} finePointer={services.finePointer ?? false}>{children}</CitationText>,
  };
  return <>
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components}>{transformedContent}</ReactMarkdown>
    {services.renderDocumentPreview(documentPreview, () => setDocumentPreview(null))}
  </>;
}
/** Source-shipped client Markdown pipeline, supplied only with host services. */
export function ChatMarkdown({ services, ...props }: ChatMarkdownProps) {
  const viewport = useMarkdownViewport();
  const resolved = { ...services, latexParsing: services.latexParsing ?? CLIENT_MARKDOWN_DEFAULTS.latexParsing,
    isMobileLayout: services.isMobileLayout ?? viewport.isMobileLayout, finePointer: services.finePointer ?? viewport.finePointer };
  return <MarkdownServicesContext.Provider value={resolved}><div className="bs-mkdown bisheng-chat-markdown"><ChatMarkdownContent {...props} /></div></MarkdownServicesContext.Provider>;
}
