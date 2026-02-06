
import { Atom, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm'

export const MessageContent = ({ text }: { text: string }) => {
    const thinkingMatch = text.match(/^:::thinking\s+([\s\S]*?)\s+:::\s*([\s\S]*)$/);
    text = text.replace(/^:::web\s+([\s\S]*?)\s+:::\s*([\s\S]*)$/, '$2').replace(/\[citation:\d+\]/g, '');

    if (thinkingMatch) {
        const thinkingContent = thinkingMatch[1];
        const mainContent = thinkingMatch[2];

        return (
            <>
                <ThinkingBlock content={thinkingContent} />
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {mainContent}
                </ReactMarkdown>
            </>
        );
    }

    return (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {text}
        </ReactMarkdown>
    );
};


const ThinkingBlock = ({ content }: { content: string }) => {
    const [isExpanded, setIsExpanded] = useState(false);

    return (
        <div className="mb-4">
            <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="flex items-center gap-2 px-3 py-2 bg-gray-100 dark:bg-zinc-800 hover:bg-gray-200 rounded-xl transition-colors text-gray-600 dark:text-gray-300"
            >
                <Atom className={`w-3 h-3 ${isExpanded ? 'animate-spin-slow' : ''}`} />
                <span className="text-xs font-medium">思考内容</span>
                {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>

            {isExpanded && (
                <div className="mt-3 ml-2 pl-4 border-l-2 border-gray-200 dark:border-zinc-700 text-gray-500 dark:text-gray-400">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {content}
                    </ReactMarkdown>
                </div>
            )}
        </div>
    );
};