import * as mammoth from 'mammoth';
import { sanitizeHtml } from '../html/sanitizeHtml';
import { usePreviewResource } from '../usePreviewResource';
import type { PreviewViewerProps } from '../viewerTypes';
import { PreviewState, readPreview, usePreviewFailure } from './PreviewState';
export function DocxViewer({ resource, zoomLevel = 100, locale, onError }: PreviewViewerProps) {
    const url = resource.previewUrl || resource.originalUrl;
    const state = usePreviewResource(url, async signal => {
        const buffer = await (await readPreview(url, signal)).arrayBuffer();
        return (await mammoth.convertToHtml({ arrayBuffer: buffer })).value;
    });
    usePreviewFailure(state.error, onError);
    if (state.status !== 'ready') return <PreviewState loading={state.status === 'loading'} locale={{ ...locale, loading: locale.docLoading }} />;
    const scale = zoomLevel / 100;

    return (
        <div className="scrollbar-os min-w-0 flex-1 overflow-auto bg-fill-1">
            <div className="box-border flex w-full justify-center py-6 px-3 sm:px-4">
                <div

                    className="w-full max-w-[800px] rounded-sm bg-white document-canvas shadow-md"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "top center",
                    }}
                >
                    <style>{`
                        .docx-content {
                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                            line-height: 1.8;
                            padding: 40px 60px;
                            font-size: 14px;
                            color: #1d2129;
                            /* Break long unbreakable tokens (URLs, ASCII art, no-space CJK runs)
                               so they wrap inside the page width instead of overflowing right. */
                            overflow-wrap: anywhere;
                            word-break: break-word;
                        }
                        /* Mobile: shrink the side padding so narrow screens
                           don't waste 120px on margins. Matches the 767px
                           breakpoint used by usePrefersMobileLayout. */
                        @media (max-width: 767px) {
                            .docx-content {
                                padding: 24px 16px;
                            }
                        }
                        .docx-content p { margin: 0 0 1em 0; }
                        /* table-layout: fixed prevents wide columns from blowing
                           out the frame; column widths from mammoth are honored
                           via <col> if present, otherwise they share width equally. */
                        .docx-content table { border-collapse: collapse; width: 100%; max-width: 100%; margin: 1em 0; table-layout: fixed; }
                        .docx-content table td, .docx-content table th { border: 1px solid #ddd; padding: 8px 12px; overflow-wrap: break-word; word-break: break-word; }
                        .docx-content table th { background: #f7f8fa; font-weight: 600; }
                        .docx-content img { max-width: 100%; height: auto; }
                        .docx-content pre, .docx-content code { white-space: pre-wrap; overflow-wrap: break-word; word-break: break-word; }
                        .docx-content h1, .docx-content h2, .docx-content h3 { color: #1d2129; margin: 1.5em 0 0.5em; }
                    `}</style>
                    <div
                        className="docx-content"
                        dangerouslySetInnerHTML={{ __html: sanitizeHtml(state.data || "") }}
                    />
                </div>
            </div>
        </div>
    );
}
