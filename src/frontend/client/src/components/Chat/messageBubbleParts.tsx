import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { useCallback, useState } from 'react';
import { useLocalize } from '~/hooks';
import { copyText } from '~/utils';
import type { AgentEvent } from '~/api/chatApi';
import DeepThinkingGroup from './Messages/DeepThinkingGroup';
import { groupEventsForDisplay, type DisplayBlock } from './Messages/groupEvents';
import Markdown from './Messages/Content/Markdown';

interface CopyButtonProps { text: string }

export function CopyButton({ text }: CopyButtonProps) {
    const localize = useLocalize();
    const [copied, setCopied] = useState(false);
    const handleCopy = useCallback((event: React.MouseEvent<HTMLButtonElement>) => {
        event.preventDefault();
        event.stopPropagation();
        copyText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    }, [text]);

    return (
        <button
            type="button"
            onClick={handleCopy}
            className="flex size-6 items-center justify-center rounded-md transition-colors hover:bg-[#F7F7F7]"
            title={localize('com_ui_copy')}
            aria-label={localize('com_ui_copy')}
        >
            {copied ? <Outlined.Copied size={14} className="text-blue-500" /> : <Outlined.Copy size={14} className="text-[#818181]" />}
        </button>
    );
}

// --- Sibling Switch (prev / next paging) ---
interface SiblingSwitchProps {
    siblingIdx: number;
    siblingCount: number;
    setSiblingIdx: (idx: number) => void;
}

export function SiblingSwitch({
    siblingIdx,
    siblingCount,
    setSiblingIdx,
}: SiblingSwitchProps) {
    if (siblingCount <= 1) return null;
    return (
        <div className="flex items-center gap-1 text-xs text-gray-400">
            <button
                type="button"
                className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
                onClick={() => setSiblingIdx(siblingIdx - 1)}
                disabled={siblingIdx === 0}
            >
                <ChevronLeftIcon size={14} />
            </button>
            <span className="tabular-nums text-[11px]">{siblingIdx + 1} / {siblingCount}</span>
            <button
                type="button"
                className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30"
                onClick={() => setSiblingIdx(siblingIdx + 1)}
                disabled={siblingIdx === siblingCount - 1}
            >
                <ChevronRightIcon size={14} />
            </button>
        </div>
    );
}

export function parseMessageText(text: string) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    if (!text) return { thinkingContent: "", webContent: [] as any[], regularContent: "" };

    // Extract thinking block
    const thinkingMatch = text.match(/:::thinking([\s\S]*?):::/);
    let regularContent = text;
    if (thinkingMatch) {
        regularContent = text.replace(/:::thinking[\s\S]*?:::/, "").trim();
    }

    // Extract web block
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    let webContent: any[] = [];
    const webMatch = regularContent.match(/:::web([\s\S]*?):::/);
    if (webMatch) {
        regularContent = regularContent.replace(/:::web[\s\S]*?:::/, "").trim();
        try {
            const str = webMatch[1].trim();
            webContent = str ? JSON.parse(str) : [];
        } catch (e) {
            console.warn("[AiChat] Failed to parse web content:", e);
        }
    }

    return {
        thinkingContent: thinkingMatch ? thinkingMatch[1].trim() : "",
        webContent,
        regularContent,
    };
}

/**
 * Render the agent-native timeline: walk `events` as display blocks and emit
 * a `DeepThinkingGroup` per non-text run + a lightweight `<Markdown>` per
 * intermediate text block. The LAST text block (if events ends with text)
 * is rendered separately by the bubble's main `<Markdown>` body so that
 * citations / copy / voice still attach to the final answer.
 */
interface AgentTimelineProps {
    events: AgentEvent[];
    isStreaming: boolean;
    /** Passed to each intermediate Markdown block; see Markdown's prop. */
    compactImages?: boolean;
    /** Index in `blocks` of the trailing text block to skip (rendered by the
     * main bubble Markdown). -1 if no such block. */
    finalTextIdx: number;
    /** Bubble's message id, used to namespace intermediate Markdown blocks. */
    messageId: string;
}

export function AgentTimeline({
    events,
    isStreaming,
    finalTextIdx,
    messageId,
    compactImages,
}: AgentTimelineProps) {
    const blocks: DisplayBlock[] = groupEventsForDisplay(events);
    const lastGroupIdx = (() => {
        for (let i = blocks.length - 1; i >= 0; i--) {
            if (blocks[i].kind === "group") return i;
        }
        return -1;
    })();

    return (
        <div className="flex w-full min-w-0 flex-col gap-3">
            {blocks.map((block, i) => {
                if (block.kind === "text") {
                    if (i === finalTextIdx) return null;
                    return (
                        <Markdown
                            key={`text-${i}`}
                            content={block.content}
                            webContent={[]}
                            citations={undefined}
                            messageId={`${messageId}-intermediate-${i}`}
                            showCursor={false}
                            isLatestMessage={false}
                            compactImages={compactImages}
                        />
                    );
                }
                return (
                    <DeepThinkingGroup
                        key={`grp-${i}`}
                        events={block.events}
                        isStreaming={isStreaming && i === lastGroupIdx && finalTextIdx === -1}
                    />
                );
            })}
        </div>
    );
}
