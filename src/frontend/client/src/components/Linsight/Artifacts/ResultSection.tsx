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
                    className="flex flex-col gap-2 rounded-xl border border-[#ececec] px-3 py-2"
                    style={{
                        backgroundImage:
                            'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'5\' height=\'5\'%3E%3Ccircle cx=\'0.5\' cy=\'0.5\' r=\'0.5\' fill=\'%23EAEEFF\'/%3E%3C/svg%3E")',
                        backgroundSize: '5px 5px',
                        backgroundColor: '#fff',
                    }}
                >
                    {/* header: icon + title + count badge */}
                    <div className="flex items-center gap-2">
                        <Outlined.Clap className="size-4 text-[#212121]" />
                        <span className="text-[14px] leading-[22px] text-[#999]">
                            {localize('com_linsight_output_files', { 0: '' }).trim()}
                        </span>
                        <span className="flex h-4 min-w-4 items-center justify-center rounded-md bg-[#212121]/5 px-1 text-[10px] font-semibold text-[#212121]">
                            {files.length}
                        </span>
                    </div>

                    {/* file list (design node 12221-40681) — each row is name on
                        the left, an always-visible "另存为" action on the right.
                        The pl-6 indent (icon 16 + gap 8) puts names under the
                        title TEXT while the hover bg spans the full row. The
                        whole row previews: the design's pointer sits mid-row,
                        not on the name, and a between-justified row is mostly
                        gap — dead gap would make the layout feel broken. */}
                    {files.map((file) => (
                        <div
                            key={file.file_id || file.file_url}
                            role="button"
                            tabIndex={0}
                            /* has-[[data-state=open]] keeps the row looking hovered
                               while its own "另存为" menu is up — by then the
                               pointer sits on the floating panel, so :hover has
                               already dropped and the row would otherwise go flat
                               under an open menu that clearly belongs to it. */
                            className="group/row flex cursor-pointer items-center justify-between gap-2 rounded-lg py-1 pl-6 pr-1 transition-colors hover:bg-[#f7f7f7] has-[[data-state=open]]:bg-[#f7f7f7]"
                            onClick={() => onPreview(file)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    onPreview(file);
                                }
                            }}
                        >
                            <span className="flex min-w-0 items-center gap-1.5 text-[14px] leading-[22px] text-[#1D2129] transition-colors group-hover/row:text-blue-700 group-has-[[data-state=open]]/row:text-blue-700">
                                <span className="truncate">{file.file_name}</span>
                                <NewTabHint file={file} />
                            </span>
                            <SaveAsButton file={file} versionId={versionId} variant="labeled" />
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
