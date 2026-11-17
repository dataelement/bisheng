import { Button } from '@bisheng/ui';

import { Atom } from 'lucide-react';
import { Outlined } from 'bisheng-icons';

import { useTranslation } from 'react-i18next';
import { useMemo, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { PlatformChatMarkdown } from '@/components/bs-comp/appChat/PlatformChatMarkdown';
import { renderGeneratedFileLink, type GeneratedFile } from './DailyGeneratedFiles';

interface MessageContentProps {
    text: string;
    /** Conversation the answer belongs to; with `files`, lets a link naming a generated file download it. */
    chatId?: string;
    files?: GeneratedFile[];
}

function withoutLegacyWebBlock(text: string): string {
    return text.replace(/^:::web\s+([\s\S]*?)\s+:::\s*([\s\S]*)$/, '$2');
}

const thinkingPattern = /^:::thinking\s+([\s\S]*?)\s+:::\s*([\s\S]*)$/;

/** Answer body the auditor sees: legacy web blocks dropped, thinking kept out of the citation text. */
export function visibleAnswerText(text: string): string {
    const stripped = withoutLegacyWebBlock(text);
    return stripped.match(thinkingPattern)?.[2] ?? stripped;
}

export const MessageContent = ({ text, chatId, files }: MessageContentProps) => {
    const stripped = withoutLegacyWebBlock(text);
    const thinkingMatch = stripped.match(thinkingPattern);
    const answer = thinkingMatch ? thinkingMatch[2] : stripped;
    const renderLink = useMemo(
        () => chatId ? (href: string, children: ReactNode) => renderGeneratedFileLink(chatId, files ?? [], href, children) : undefined,
        [chatId, files],
    );

    return (
        <>
            {thinkingMatch && <ThinkingBlock content={thinkingMatch[1]} />}
            <PlatformChatMarkdown content={answer} renderLink={renderLink} />
        </>
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
