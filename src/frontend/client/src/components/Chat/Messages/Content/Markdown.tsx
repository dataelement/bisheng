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
import { useFileDownload } from '~/data-provider';
import { PermissionTypes, Permissions } from '~/data-provider/data-provider/src';
import useHasAccess from '~/hooks/Roles/useHasAccess';
import useLocalize from '~/hooks/useLocalize';
import store from '~/store';
import { handleDoubleClick, langSubset, preprocessLaTeX } from '~/utils';
import { WebItem } from './SearchWebUrls';

const ECharts = lazy(() => import('./Echarts'));
const MermaidBlock = lazy(() => import('./Mermaid'));

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
    if (lang === 'echarts') return <Suspense fallback={<div>...</div>}>
      <ECharts option={children} />
    </Suspense>
    if (lang === 'mermaid') return <Suspense fallback={<div>...</div>}>
      <MermaidBlock>{String(children).trim()}</MermaidBlock>
    </Suspense>
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
};

const Citation = ({ data, children }) => {

  if (!data) return null;

  return <TooltipAnchor
    role="button"
    description={
      <div className="p-2">
        <WebItem {...data} />
      </div>
    }
    className="bg-gray-100 dark:bg-gray-600 inline-flex size-5 items-center justify-center rounded-full transition-colors duration-200 hover:bg-surface-hover"
    onClick={() => {
      window.open(data.url, '_blank')
    }}
  >
    <span className='text-xs'>{children}</span>
  </TooltipAnchor>
};

const Markdown = memo(({ content = '', showCursor, isLatestMessage, webContent }: TContentProps & { webContent: any }) => {
  const LaTeXParsing = useRecoilValue<boolean>(store.LaTeXParsing);
  const isInitializing = content === '';

  const currentContent = useMemo(() => {
    if (isInitializing) {
      return '';
    }
    const message = LaTeXParsing ? preprocessLaTeX(content) : content;
//         return `\`\`\`mermaid
//     graph TD
//       A[Next.js] --> B[Markdoc]
//       B --> C[Mermaid Node]
//       C --> D[渲染流程图]
//       D --> E{交互式图表}
// \`\`\``;
//     return `\`\`\`echarts
// {"xAxis":{"type":"category","data":["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]},"yAxis":{"type":"value"},"series":[{"data":[120,200,150,80,70,110,130],"type":"bar"}]}
// \`\`\``
    return message
      // .replaceAll(/(\n\s{4,})/g, '\n   ') // 禁止4空格转代码
      .replace(/(?<![\n\|])\n(?!\n)/g, '\n\n') // 单个换行符 处理不换行情况，例如：`Hello | There\nFriend
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

  if (isInitializing) {
    return (
      <div className="absolute">
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
                  const parts = children.split(/\[citation:(\d+)\]/g);
                  return (
                    <>
                      {parts.map((part, index) => {
                        if (index % 2 === 0) {
                          return part;
                        } else {
                          return webContent?.[Number(part) - 1] ? <Citation key={index} data={webContent[Number(part) - 1]}>{part}</Citation> : null;
                        }
                      })}
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
