import { useRef, type ReactNode } from 'react';
import { DiagramBlock } from './DiagramBlock';
import { CopyMessageAction } from '../components/CopyMessageAction';
import { useMarkdownServices } from './MarkdownServices';
export function MarkdownCode({ className, children }: { className?: string; children?: ReactNode }) {
  const services = useMarkdownServices();
  const codeRef = useRef<HTMLElement>(null);
  const code = String(children ?? '');
  const language = /language-(\w+)/.exec(className ?? '')?.[1] ?? 'text';
  const inline = typeof children === 'string' && children.split('\n').length === 1;
  const props = { language, code, inline, className, codeRef };
  if (language === 'math') return <>{children}</>;
  if (inline) return <code className={className} onDoubleClick={event => {
    const range = document.createRange(); range.selectNodeContents(event.currentTarget);
    const selection = window.getSelection(); if (selection) { selection.removeAllRanges(); selection.addRange(range); }
  }}>{children}</code>;
  if (language === 'echarts' || language === 'mermaid') return <DiagramBlock language={language} code={code} />;
  return <div className="w-full rounded-md border border-[#E0E0E0] bg-[#F6F8FA] text-xs text-[#24292e]">
    <div className="relative flex items-center justify-between rounded-tl-md rounded-tr-md border-b border-[#E0E0E0] bg-fill-3 px-4 py-2 font-sans text-xs text-[#57606A]">
      <span className="text-sm font-medium">{language}</span><div className="flex items-center gap-4">{services.renderCodeActions?.(props)}
        <CopyMessageAction showLabel label={services.localize('shared:app_chat.copy_code')} copiedLabel={services.localize('shared:app_chat.copied')}
          onCopy={() => services.copyText(codeRef.current?.textContent?.trim() ?? code.trim())} />
      </div>
    </div>
    <div className="overflow-y-auto scrollbar-on-scroll p-4"><code ref={codeRef} className={`hljs language-${language} !whitespace-pre`}>{children}</code></div>
  </div>;
}
