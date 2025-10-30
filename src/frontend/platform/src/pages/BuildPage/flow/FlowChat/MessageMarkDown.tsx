import { CodeBlock } from "@/modals/formModal/chatMessage/codeBlock";
import Echarts from "@/workspace/markdown/Echarts";
import MermaidBlock from "@/workspace/markdown/Mermaid";
import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeMathjax from "rehype-mathjax";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

const MessageMarkDown = React.memo(function MessageMarkDown({ message }) {
    function filterMermaidBlocks(input) {
        const closedMermaidPattern = /```mermaid[\s\S]*?```/g;
        const openMermaidPattern = /```mermaid[\s\S]*$/g;

        // 先删除未闭合的
        if (!closedMermaidPattern.test(input)) {
            input = input.replace(openMermaidPattern, "");
        }

        return input;
    }

    const processedMessage = useMemo(() => {
        return filterMermaidBlocks(message)
            .replaceAll(/(\n\s{4,})/g, '\n   ') // 禁止4空格转代码
            .replace(/(?<![\n\|])\n(?!\n)/g, '\n\n') // 单个换行符 处理不换行情况，例如：`Hello|There\nFriend
            .replaceAll('(bisheng/', '(/bisheng/') // TODO 临时处理方案,以后需要改为markdown插件方式处理
            .replace(/\\[\[\]]/g, '$$') // 处理`\[...\]`包裹的公式
    }, [message]);

    return (
        <div className="bs-mkdown inline-block break-all max-w-full text-sm text-text-answer">
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeMathjax]}
                components={{
                    a: ({ node, href, children }) => {
                        return <a href={href} target="_blank" rel="noreferrer" className="text-primary underline hover:text-primary/80">{children}</a>
                    },
                    code: ({ node, className, children }) => {
                        const match = /language-(\w+)/.exec(className ?? '');
                        const lang = match && match[1];

                        if (lang === 'echarts') return <Echarts option={children} />
                        if (lang === 'mermaid') return <MermaidBlock>{String(children).trim()}</MermaidBlock>

                        return <CodeBlock
                            key={Math.random()}
                            language={lang}
                            value={String(children).replace(/\n$/, "")}
                        />
                    },
                }}
            >
                {processedMessage}
            </ReactMarkdown>
        </div>
    );
});


export default MessageMarkDown;