import { useState } from 'react';
import { cn } from '@bisheng/ui';
import { usePreviewResource } from '../usePreviewResource';
import type { PreviewViewerProps } from '../viewerTypes';
import { MarkdownBody } from './MarkdownViewer';
import { readPreview, usePreviewFailure } from './PreviewState';
import { extractMarkdownSection, parseTranscriptCues } from './transcript';
// eslint-disable-next-line no-restricted-syntax -- Backend data heading, not user interface copy.
const RECOGNIZED_SECTION = "识别文本";
// eslint-disable-next-line no-restricted-syntax -- Backend data heading, not user interface copy.
const ENTRY_SECTION = "入库文本";
const TRANSCRIPT_MARKDOWN_SIZE = '!text-body';
function TranscriptCueList({ cues }: { cues: Array<{ time: string; text: string }> }) {
    return (
        <ol className="space-y-4">
            {cues.map((cue, index) => (
                <li key={`${cue.time}-${index}`}>
                    <div className="text-caption tabular-nums text-text-3">{cue.time}</div>
                    <p className="mt-1 text-body text-text-1">{cue.text}</p>
                </li>
            ))}
        </ol>
    );
}


interface TranscriptProps extends PreviewViewerProps { className?: string; bottomInset?: number }
export function MediaTranscriptTabs({ resource, locale, className, onError, bottomInset = 16 }: TranscriptProps) {
    const [activeTab, setActiveTab] = useState<'recognized' | 'entry'>('recognized');
    const url = resource.previewUrl;
    const state = usePreviewResource(url, async signal => (await readPreview(url, signal)).text());
    usePreviewFailure(state.error, onError);
    const content = state.data || '';
    const loading = state.status === 'loading';
    const error = state.status === 'error' ? locale.failed : '';
    const entryText = extractMarkdownSection(content, ENTRY_SECTION) || content;
    const recognizedText = extractMarkdownSection(content, RECOGNIZED_SECTION) || content;
    const activeContent = activeTab === "recognized" ? recognizedText : entryText;
    const { preamble, cues } = parseTranscriptCues(activeContent);

    return (
        <section className={cn("flex h-full min-h-0 flex-col bg-white", className)}>
            {/* 12px inset: the segmented control's own 3px padding lines its label
                up with the 16px-inset transcript text below. */}
            <div className="flex shrink-0 items-center px-3 pt-4">
                {/* Segmented control — mirrors the include/exclude tabs in
                    Subscription/CreateChannel/FilterConditionEditor. */}
                <div className="flex flex-shrink-0 rounded-[6px] bg-fill-1 p-[3px]">
                    <button
                        type="button"
                        onClick={() => setActiveTab("recognized")}
                        className={`whitespace-nowrap rounded-sm px-[12px] py-[2px] text-center text-[14px] leading-[22px] transition-colors ${activeTab === "recognized"
                            ? "bg-blue-500/15 font-medium text-blue-500"
                            : "bg-transparent text-text-3 hover:bg-fill-2"}`}
                    >
                        {locale.recognizedText}
                    </button>
                    <button
                        type="button"
                        onClick={() => setActiveTab("entry")}
                        className={`whitespace-nowrap rounded-sm px-[12px] py-[2px] text-center text-[14px] leading-[22px] transition-colors ${activeTab === "entry"
                            ? "bg-blue-500/15 font-medium text-blue-500"
                            : "bg-transparent text-text-3 hover:bg-fill-2"}`}
                    >
                        {locale.entryText}
                    </button>
                </div>
            </div>
            {loading ? (
                <div className="flex flex-1 items-center justify-center text-sm text-text-3">
                    {locale.loading}
                </div>
            ) : error ? (
                <div className="flex flex-1 items-center justify-center text-sm text-text-3">{error}</div>
            ) : (
                // pb clears the AI dock pinned at the bottom of the page.
                <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-3" style={{ paddingBottom: bottomInset }}>
                    {cues.length ? (
                        <>
                            {preamble ? <MarkdownBody content={preamble} className={TRANSCRIPT_MARKDOWN_SIZE} /> : null}
                            <TranscriptCueList cues={cues} />
                        </>
                    ) : (
                        <MarkdownBody content={activeContent} className={TRANSCRIPT_MARKDOWN_SIZE} />
                    )}
                </div>
            )}
        </section>
    );
}
