import React, { lazy, memo, Suspense, useEffect, useMemo, useRef } from 'react';
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
import { TooltipAnchor } from '~/components/ui';
import { useFileDownload } from '~/hooks/queries/data-provider';
import { PermissionTypes, Permissions } from '~/types/chat';
import useHasAccess from '~/hooks/Roles/useHasAccess';
import useLocalize from '~/hooks/useLocalize';
import store from '~/store';
import { handleDoubleClick, langSubset, preprocessLaTeX } from '~/utils';
import type { ChatCitation } from '~/api/chatApi';
import { WebItem } from './SearchWebUrls';
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
    if (lang === 'echarts') return <Echarts option={children} />
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

type CitationDisplayData = {
  label: number;
  type: string;
  groupKey: string;
  chunkId: string;
  url?: string;
  title: string;
  snippet: string;
};

const CITATION_START = '\ue200';
const CITATION_SEPARATOR = '\ue201';
const CITATION_END = '\ue202';

type ParsedCitationRef = {
  type: string;
  groupKey: string;
  chunkId: string;
  citationId: string;
  itemId: string;
};

function parseCitationRef(ref: string): ParsedCitationRef | null {
  const lastColonIndex = ref.lastIndexOf(':');
  if (lastColonIndex < 0) {
    return null;
  }

  const citationId = ref.slice(0, lastColonIndex).trim();
  const itemId = ref.slice(lastColonIndex + 1).trim();

  if (!citationId || !itemId) {
    return null;
  }

  const firstUnderscoreIndex = citationId.indexOf('_');
  if (firstUnderscoreIndex < 0) {
    return null;
  }

  const type = citationId.slice(0, firstUnderscoreIndex).trim();
  const groupKey = citationId.slice(firstUnderscoreIndex + 1).trim();

  if (!type || !groupKey) {
    return null;
  }

  return {
    type,
    groupKey,
    chunkId: itemId,
    citationId,
    itemId,
  };
}

function buildCitationDisplayData(ref: string, citations: ChatCitation[] | null | undefined): CitationDisplayData | null {
  if (!citations?.length) {
    return null;
  }

  const parsedRef = parseCitationRef(ref);
  if (!parsedRef) {
    return null;
  }

  const { citationId, itemId, type, groupKey, chunkId } = parsedRef;
  const citation = citations.find((item) => item.citationId === citationId);

  if (!citation?.sourcePayload) {
    return null;
  }

  const matchedItem = citation.sourcePayload.items?.find((item) => String(item.itemId) === itemId);
  const title =
    citation.sourcePayload.title ||
    citation.sourcePayload.documentName ||
    citation.sourcePayload.knowledgeName ||
    matchedItem?.title ||
    citationId;
  const snippet =
    matchedItem?.content ||
    matchedItem?.snippet ||
    citation.sourcePayload.snippet ||
    '';
  const url =
    citation.sourcePayload.url ||
    citation.sourcePayload.sourceUrl ||
    citation.sourcePayload.previewUrl ||
    citation.sourcePayload.downloadUrl;

  return {
    label: 0,
    type,
    groupKey,
    chunkId,
    url,
    title,
    snippet,
  };
}

function transformPrivateCitations(content: string, citations: ChatCitation[] | null | undefined) {
  if (!content.includes(CITATION_START)) {
    return { transformedContent: content, citationMap: {} as Record<string, CitationDisplayData> };
  }

  const citationMap: Record<string, CitationDisplayData> = {};
  const groupIndexMap: Record<string, number> = {};
  let nextGroupLabel = 1;
  const transformedContent = content.replace(new RegExp(`${CITATION_START}([\\s\\S]*?)${CITATION_END}`, 'g'), (_, rawRefs: string) => {
    const refs = rawRefs
      .split(CITATION_SEPARATOR)
      .map((item) => item.trim())
      .filter(Boolean);

    return refs
      .map((ref) => {
        if (!citationMap[ref]) {
          const displayData = buildCitationDisplayData(ref, citations);
          if (displayData) {
            const groupId = `${displayData.type}_${displayData.groupKey}`;
            if (!groupIndexMap[groupId]) {
              groupIndexMap[groupId] = nextGroupLabel;
              nextGroupLabel += 1;
            }
            displayData.label = groupIndexMap[groupId];
            citationMap[ref] = displayData;
          }
        }
        return citationMap[ref] ? `[citationref:${ref}]` : '';
      })
      .join('');
  });

  return { transformedContent, citationMap };
}

const Citation = ({ data, children }) => {

  if (!data) return null;

  const citationLabel = String(children ?? '');
  const normalizedType = data.type.toLowerCase();
  const isWebCitation = normalizedType === 'web' || normalizedType === 'websearch';
  const citationClassName = isWebCitation
    ? 'bg-[#F3EEFF] text-[#7C3AED] hover:bg-[#E9DFFF]'
    : 'bg-[#EEF3FF] text-[#1D4ED8] hover:bg-[#E3ECFF]';

  return <TooltipAnchor
    role="button"
    description={
      <div className="p-2">
        <WebItem url={data.url || '#'} title={data.title} snippet={data.snippet} />
      </div>
    }
    className={`ml-1 inline-flex min-h-6 min-w-6 items-center justify-center rounded-xl px-2 py-0.5 text-[0.9em] font-medium leading-none transition-colors duration-200 ${citationClassName}`}
    onClick={() => {
      if (data.url) {
        window.open(data.url, '_blank')
      }
    }}
  >
    <span>{children}</span>
  </TooltipAnchor>
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
    const { transformedContent, citationMap } = transformPrivateCitations(normalizedContent, citations);

    return {
      currentContent: transformedContent,
      citationMap,
    };
    // .replaceAll('(bisheng/', '(/bisheng/') // TODO 临时处理方案,以后需要改为markdown插件方式处理
    // .replace(/\\[\[\]]/g, '$$') // 处理`\[...\]`包裹的公式
  }, [content, LaTeXParsing, isInitializing, citations]);

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
                          <Citation key={`legacy-${matchIndex}`} data={webContent[legacyIndex - 1]}>
                            {legacyIndexValue}
                          </Citation>
                        );
                      }
                    } else if (privateRef) {
                      const citationData = citationMap[privateRef];
                      if (citationData) {
                        nodes.push(
                          <Citation key={`private-${matchIndex}`} data={citationData}>
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
