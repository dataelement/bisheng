/**
 * F035 Track H (P4): final-result artifact delivery (spec §5, fig 8/12).
 * Rendered in the ExecutionFlow `execution-artifacts` slot once the run
 * completes: report link row → answer markdown → output files card.
 */
import { useCallback } from 'react';
import { Outlined } from 'bisheng-icons';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { useLocalize } from '~/hooks';
import '~/markdown.css';
import { type ArtifactFile, resolveDeliverableLink, stripWorkspacePaths } from './artifactUtils';
import { NewTabHint } from './NewTabHint';
import { SaveAsButton } from './SaveAsButton';

interface ResultSectionProps {
    /** output_result.answer — the run summary, markdown */
    answer?: string;
    /** output_result.final_files (store file_list) */
    files: ArtifactFile[];
    versionId: string;
    onPreview: (file: ArtifactFile) => void;
}

export function ResultSection({ answer, files, versionId, onPreview }: ResultSectionProps) {
    const localize = useLocalize();
    const resolveArtifactLink = useCallback(
        (href: string) => resolveDeliverableLink(files, href),
        [files],
    );
    // Primary deliverable = files[0] (spec §5: report link row). The backend ranks
    // the list by file TYPE then recency, so [0] is the headline artifact (a report
    // outranks the charts it rendered afterwards), not just the newest write.
    const primaryFile = files[0];
    // With several deliverables the row names the headline file AND says how many
    // there are in total — naming one of five silently would misrepresent the run,
    // and a bare count would waste the row. The full manifest is the card below.
    const multiple = files.length > 1;
    const fileCount = String(files.length);

    return (
        <div className="space-y-3">
            {/* report link row */}
            {primaryFile && (
                <div className="flex items-center gap-1.5 text-sm text-gray-800">
                    <span className="shrink-0">
                        {multiple
                            ? localize('com_linsight_files_ready_prefix', { 0: fileCount })
                            : localize('com_linsight_report_ready')}
                    </span>
                    <button
                        type="button"
                        className="flex min-w-0 items-center gap-1 text-blue-600 transition-colors hover:text-blue-700"
                        onClick={() => onPreview(primaryFile)}
                    >
                        <Outlined.File size={14} className="shrink-0" />
                        <span className="truncate">{primaryFile.file_name}</span>
                        <NewTabHint file={primaryFile} className="text-blue-600/60" />
                    </button>
                    {/* shrink-0 so a long file name truncates but the "等 N 个文件"
                        count stays fully visible — otherwise the user never learns
                        there are more files than the one named. */}
                    {multiple && (
                        <span className="shrink-0">
                            {localize('com_linsight_files_ready_suffix', { 0: fileCount })}
                        </span>
                    )}
                    {/* Sole deliverable → this sentence IS the whole hand-off (the
                        file card below only renders for multi-file runs), so the
                        download belongs here. With several files the card carries
                        one per row; repeating it after "等 N 个文件" would read as
                        "download all", which is not what it does.
                        `inline` (always visible), not the list rows' hover-reveal:
                        a lone glyph in a sentence isn't the repetition that made a
                        column of them read as noise, and this is the only download
                        entry a single-file run has — the exact gap this fixed. */}
                    {!multiple && (
                        <SaveAsButton file={primaryFile} versionId={versionId} variant="inline" />
                    )}
                </div>
            )}

            {/* answer summary, markdown rendered — plain paragraphs flush with the
                report-link row above (no card chrome), matching the delivery design. */}
            {answer && (
                <div className="bs-mkdown text-sm leading-6 text-gray-800 [&_p:last-child]:mb-0">
                    {/* strip internal output/ · scratch/ paths the model may have
                        echoed from a tool result — users don't need the workspace zone */}
                    <Markdown
                        content={stripWorkspacePaths(answer)}
                        isLatestMessage={true}
                        webContent={false}
                        resolveArtifactLink={resolveArtifactLink}
                        // Markdown types the callback as (file: unknown) — the resolver
                        // it pairs with only ever yields ArtifactFile values here.
                        onArtifactPreview={onPreview as (file: unknown) => void}
                    />
                </div>
            )}

            {/* output files card — dotted background matching ClarifyCard.
                Only shown for multi-file runs because the report-link row already
                surfaces a single deliverable. In-answer links still resolve to the
                matching artifact and open the same preview. */}
            {files.length > 1 && (
                <div
                    className="rounded-2xl border border-[#EEF2F6] p-5 shadow-[0_4px_20px_rgba(0,0,0,0.03)]"
                    style={{
                        backgroundImage:
                            'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'5\' height=\'5\'%3E%3Ccircle cx=\'0.5\' cy=\'0.5\' r=\'0.5\' fill=\'%23EAEEFF\'/%3E%3C/svg%3E")',
                        backgroundSize: '5px 5px',
                        backgroundColor: '#fff',
                    }}
                >
                    {/* header: icon + title + count badge. px-1 matches the file
                        rows so the list aligns under the title. */}
                    <div className="flex items-center gap-2 px-1 pb-4">
                        <Outlined.Clap className="size-4 text-text-1" />
                        <span className="text-[14px] font-medium text-text-3">
                            {localize('com_linsight_output_files', { 0: '' }).trim()}
                        </span>
                        <span className="flex h-[18px] min-w-[16px] items-center justify-center rounded-full bg-gray-100 px-1.5 text-caption-sm text-[#666]">
                            {files.length}
                        </span>
                    </div>

                    {/* file list — the indent lives on each row's pl-7 (icon 16 +
                        gap 8 + header px-1 4) so names align under the title TEXT
                        while the hover background still spans the full row width.
                        Hover bg #f7f7f7 per design (node 12221-40681). */}
                    <div className="space-y-1">
                        {files.map((file) => (
                            <div
                                key={file.file_id || file.file_url}
                                className="group/row flex items-center gap-1 rounded-lg py-1.5 pl-7 pr-2 transition-colors hover:bg-[#f7f7f7]"
                            >
                                {/* Name = preview, and the action sits right after
                                    it rather than in a far-right gutter — the name
                                    is what the download is ABOUT, so it should not
                                    have to be traced across the row. The name is
                                    min-w-0 but NOT flex-1: it shrinks to its text
                                    and only truncates when the row runs out. */}
                                <button
                                    type="button"
                                    className="flex min-w-0 items-center gap-1.5 text-left text-[14px] text-[#1A1A1A] transition-colors hover:text-blue-500"
                                    onClick={() => onPreview(file)}
                                >
                                    <span className="truncate">{file.file_name}</span>
                                    <NewTabHint file={file} />
                                </button>
                                <SaveAsButton file={file} versionId={versionId} />
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
