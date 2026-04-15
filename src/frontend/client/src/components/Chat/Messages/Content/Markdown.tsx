import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { ExternalLink, FileText, Globe2, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useRecoilValue } from 'recoil';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import remarkDirective from 'remark-directive';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import supersub from 'remark-supersub';
import type { Pluggable } from 'unified';
import {
  ArtifactProvider,
  CodeBlockProvider,
  useCodeBlockContext,
  useToastContext,
} from '~/Providers';
import { Artifact, artifactPlugin } from '~/components/Artifacts/Artifact';
import { remarkCitationPlugin } from '~/components/Artifacts/remarkCitationPlugin';
import CodeBlock from '~/components/Messages/Content/CodeBlock';
import { useFileDownload } from '~/hooks/queries/data-provider';
import { PermissionTypes, Permissions } from '~/types/chat';
import useHasAccess from '~/hooks/Roles/useHasAccess';
import useLocalize from '~/hooks/useLocalize';
import store from '~/store';
import { handleDoubleClick, langSubset, preprocessLaTeX } from '~/utils';
import { getCitationDetail, type ChatCitation } from '~/api/chatApi';
import {
  buildCitationPreview,
  createCitationDetailMap,
  getCitationClassName,
  getCitationSourceLabel,
  getLegacyCitationPreview,
  transformPrivateCitations,
  type CitationDetailLoader,
  type CitationDisplayData,
  type CitationPreview,
} from './citationUtils';
import MermaidBlock from './Mermaid'
import Echarts from './Echarts'

// const ECharts = lazy(() => import('./Echarts')); // cdn
// const MermaidBlock = lazy(() =>
//   import(
//     /* webpackChunkName: "mermaid" */
//     /* webpackPrefetch: false */
//     /* webpackPreload: false */
//     './Mermaid'
//   )
// );

type TCodeProps = {
  inline?: boolean;
  className?: string;
  children: React.ReactNode;
};

export const code: React.ElementType = memo(({ className, children }: TCodeProps) => {
  const canRunCode = useHasAccess({
    permissionType: PermissionTypes.RUN_CODE,
    permission: Permissions.USE,
  });
  const match = /language-(\w+)/.exec(className ?? '');
  const lang = match && match[1];
  const isMath = lang === 'math';
  const isSingleLine = typeof children === 'string' && children.split('\n').length === 1;

  const { getNextIndex, resetCounter } = useCodeBlockContext();
  const blockIndex = useRef(getNextIndex(isMath || isSingleLine)).current;

  useEffect(() => {
    resetCounter();
  }, [children, resetCounter]);

  if (isMath) {
    return <>{children}</>;
  } else if (isSingleLine) {
    return (
      <code onDoubleClick={handleDoubleClick} className={className}>
        {children}
      </code>
    );
  } else {
    if (lang === 'echarts') return <Echarts option={String(children)} />
    if (lang === 'mermaid') return <MermaidBlock>{String(children).trim()}</MermaidBlock>
    return <CodeBlock
      lang={lang ?? 'text'}
      codeChildren={children}
      blockIndex={blockIndex}
      allowExecution={canRunCode}
    />
  }
});

export const codeNoExecution: React.ElementType = memo(({ className, children }: TCodeProps) => {
  const match = /language-(\w+)/.exec(className ?? '');
  const lang = match && match[1];

  if (lang === 'math') {
    return children;
  } else if (typeof children === 'string' && children.split('\n').length === 1) {
    return (
      <code onDoubleClick={handleDoubleClick} className={className}>
        {children}
      </code>
    );
  } else {
    return <CodeBlock lang={lang ?? 'text'} codeChildren={children} allowExecution={false} />;
  }
});

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
          status: 'error',
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
};

function CitationPreviewCard({
  preview,
  label,
  isLoading,
  error,
}: {
  preview: CitationPreview | null;
  label?: number;
  isLoading: boolean;
  error: boolean;
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

  const isWeb = preview.type === 'web';
  const Icon = isWeb ? Globe2 : FileText;

  return (
    <div className="w-[420px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg bg-white text-[#1D2129] shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
      <div className="flex items-center gap-2 border-b border-[#F2F3F5] px-4 py-3">
        <Icon className={`size-4 shrink-0 ${isWeb ? 'text-[#7C3AED]' : 'text-[#F53F3F]'}`} />
        {preview.link ? (
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
            {preview.snippet || '暂无内容摘要'}
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between gap-3 text-[13px] leading-5 text-[#86909C]">
          <div className="flex min-w-0 items-center gap-2">
            <Icon className="size-4 shrink-0" />
            <span className="truncate">{preview.sourceName}</span>
            {preview.sourceMeta && <span className="shrink-0">{preview.sourceMeta}</span>}
          </div>
          <div className={`shrink-0 rounded px-2 py-1 ${isWeb ? 'bg-[#F3EEFF] text-[#7C3AED]' : 'bg-[#EEF3FF] text-[#165DFF]'}`}>
            [{label}] - {isWeb ? '网页' : '文档'}
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
}: {
  data: Partial<CitationDisplayData>;
  children: React.ReactNode;
  initialDetail?: ChatCitation | null;
  webContent?: any;
  loadCitationDetail: CitationDetailLoader;
}) => {
  if (!data) return null;

  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ChatCitation | null>(initialDetail ?? null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(false);
  const closeTimerRef = useRef<number | null>(null);
  const citationClassName = getCitationClassName(data.type);
  const legacyPreview = data.ref?.startsWith('citation:')
    ? getLegacyCitationPreview(webContent, data.label)
    : null;
  const preview = legacyPreview ?? buildCitationPreview(detail, data);

  const fetchDetail = async () => {
    if (detail || legacyPreview || isLoading || !data.citationId || data.citationId.startsWith('citation:')) {
      return;
    }

    setIsLoading(true);
    setError(false);
    try {
      const nextDetail = await loadCitationDetail(data.citationId);
      setDetail(nextDetail);
    } catch (err) {
      console.error('Failed to load citation detail:', err);
      setError(true);
    } finally {
      setIsLoading(false);
    }
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
    <Popover.Root open={open} onOpenChange={handleOpenChange}>
      <Popover.Trigger asChild>
        <button
          type="button"
          data-citation-ref={data.ref}
          data-citation-id={data.citationId}
          data-citation-item-id={data.itemId}
          data-citation-type={data.type}
          data-citation-group-key={data.groupKey}
          data-citation-chunk-id={data.chunkId}
          aria-label={`${getCitationSourceLabel(data.type)}引用 ${data.label ?? ''}`}
          onMouseEnter={() => handleOpenChange(true)}
          onMouseLeave={scheduleClose}
          className={`ml-1 inline-flex min-h-6 min-w-6 cursor-pointer items-center justify-center rounded-xl px-2 py-0.5 text-[0.9em] font-medium leading-none transition-colors duration-200 ${citationClassName}`}
        >
          <span>{children}</span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={8}
          onMouseEnter={() => handleOpenChange(true)}
          onMouseLeave={scheduleClose}
          className="z-50 outline-none"
        >
          <CitationPreviewCard
            preview={preview}
            label={data.label}
            isLoading={isLoading}
            error={error}
          />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
};

const Markdown = memo(({ content = '', showCursor, isLatestMessage, webContent, citations }: TContentProps & { webContent: any }) => {
  const LaTeXParsing = useRecoilValue<boolean>(store.LaTeXParsing);
  const isInitializing = content === '';

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
    const normalizedContent = filterMermaidBlocks(message)
      // .replaceAll(/(\n\s{4,})/g, '\n   ') // 禁止4空格转代码
      .replace(/(?<![\n\|])\n(?!\n)/g, '\n\n') // 单个换行符 处理不换行情况，例如：`Hello | There\nFriend
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

  const citationDetailMap = useMemo(() => createCitationDetailMap(citations), [citations]);
  const citationDetailCacheRef = useRef<Record<string, ChatCitation>>({});
  const citationRequestCacheRef = useRef<Record<string, Promise<ChatCitation | null>>>({});

  useEffect(() => {
    Object.entries(citationDetailMap).forEach(([citationId, detail]) => {
      citationDetailCacheRef.current[citationId] = detail;
    });
  }, [citationDetailMap]);

  const loadCitationDetail = useCallback<CitationDetailLoader>(async (citationId) => {
    const cachedDetail = citationDetailCacheRef.current[citationId];
    if (cachedDetail) {
      return cachedDetail;
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
  }, []);

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
              a,
              p,
              artifact: Artifact,
              citation: ({ children }: { children: React.ReactNode }) => {
                if (typeof children === 'string') {
                  const citationPattern = /\[citation:(\d+)\]|\[citationref:([^\]]+)\]/g;
                  const nodes: React.ReactNode[] = [];
                  let lastIndex = 0;

                  for (const match of children.matchAll(citationPattern)) {
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
      </CodeBlockProvider>
    </ArtifactProvider>
  );
});

export default Markdown;
