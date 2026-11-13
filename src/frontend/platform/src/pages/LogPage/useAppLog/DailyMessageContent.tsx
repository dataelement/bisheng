import { Button } from '@bisheng/ui';

import { Atom } from 'lucide-react';
import { Outlined } from 'bisheng-icons';

import { useTranslation } from 'react-i18next';
import { useMemo, useState, type ComponentPropsWithoutRef } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm'
import { renderGeneratedFileLink, type GeneratedFile } from './DailyGeneratedFiles';

interface MessageContentProps {
    text: string;
    /** Conversation the answer belongs to; with `files`, lets a link naming a generated file download it. */
    chatId?: string;
    files?: GeneratedFile[];
}

export const MessageContent = ({ text, chatId, files }: MessageContentProps) => {
    const components = useMemo<Components | undefined>(() => {
        if (!chatId) return undefined;
        return {
            a: ({ href, title, children }: ComponentPropsWithoutRef<'a'>) =>
                <>{renderGeneratedFileLink(chatId, files ?? [], href, children) ?? <a href={href} title={title}>{children}</a>}</>,
        };
    }, [chatId, files]);

    const thinkingMatch = text.match(/^:::thinking\s+([\s\S]*?)\s+:::\s*([\s\S]*)$/);
    text = text.replace(/^:::web\s+([\s\S]*?)\s+:::\s*([\s\S]*)$/, '$2').replace(/\[citation:\d+\]/g, '');

    if (thinkingMatch) {
        const thinkingContent = thinkingMatch[1];
        const mainContent = thinkingMatch[2];

        return (
            <>
                <ThinkingBlock content={thinkingContent} />
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
                    {mainContent}
                </ReactMarkdown>
            </>
        );
    }

    return (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
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