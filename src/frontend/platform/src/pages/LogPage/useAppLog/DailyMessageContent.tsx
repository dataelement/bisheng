import { Button } from '@bisheng/ui';

import { Atom } from 'lucide-react';
import { Outlined } from 'bisheng-icons';

import { useTranslation } from 'react-i18next';
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
    const { t } = useTranslation();
    const [isExpanded, setIsExpanded] = useState(false);

    return (
        <div className="mb-4">
            <Button type="button" variant="text" size="small" aria-expanded={isExpanded} onClick={() => setIsExpanded(!isExpanded)} color="default">
                <Atom className={`w-3 h-3 ${isExpanded ? 'animate-spin-slow' : ''}`} />
                <span>{t('log.thinkingContent')}</span>
                {isExpanded ? <Outlined.Up size={14} /> : <Outlined.Down size={14} />}
            </Button>

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