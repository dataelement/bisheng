import React, { memo, useEffect, useRef } from 'react';
import { useCodeBlockContext } from '~/Providers';
import { handleDoubleClick } from '~/utils';
import useHasAccess from '~/hooks/Roles/useHasAccess';
import { Permissions, PermissionTypes } from '~/types/chat';
import CodeBlock from '~/components/Messages/Content/CodeBlock';
import Echarts from './Echarts';
import MermaidBlock from './Mermaid';
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

