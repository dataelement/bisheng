/**
 * FilePreview — pure, reusable file preview component.
 * Renders TopBar + optional Sidebar + format-specific Viewer.
 * Width: 100% — the parent controls sizing.
 * AI assistant and split-pane logic live in the parent (FilePreviewPage).
 */
import * as pdfjsLib from "pdfjs-dist";
import { useCallback, useEffect, useState } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { getViewerType, supportsPagination, supportsSidebar, supportsZoom } from "./viewers";
import { DocxViewer } from "./viewers/DocxViewer";
import { HtmlViewer } from "./viewers/HtmlViewer";
import { ImageViewer } from "./viewers/ImageViewer";
import { MarkdownViewer } from "./viewers/MarkdownViewer";
import { PdfViewer } from "./viewers/PdfViewer";
import { TextViewer } from "./viewers/TextViewer";
import { XlsxViewer } from "./viewers/XlsxViewer";
import { useLocalize } from "~/hooks";
import type { CitationPdfBBox } from "~/components/Chat/Messages/Content/citationUtils";

export interface FilePreviewProps {
    /** File display name (with extension) */
    fileName: string;
    /** File extension, e.g. "pdf", "docx" */
    fileType: string;
    /** Full URL to the file */
    fileUrl: string;
    /** Extra actions rendered in TopBar right area (before download button) */
    actions?: React.ReactNode;
    /** True when pptx-to-pdf conversion failed on the backend */
    conversionFailed?: boolean;
    /** Optional PDF highlight boxes in original PDF coordinates. */
    highlightBboxes?: CitationPdfBBox[];
    /** Optional PDF box to scroll into view. */
    targetBBox?: CitationPdfBBox | null;
    /** Render viewer-only layout (hide top toolbar and sidebar controls). */
    compactMode?: boolean;
    /** Whether to expose download actions. */
    allowDownload?: boolean;
    /** Optional business-level download handler. Defaults to downloading fileUrl. */
    onDownloadFile?: () => void;
}

export default function FilePreview({
    fileName,
    fileType,
    fileUrl,
    actions,
    conversionFailed = false,
    highlightBboxes = [],
    targetBBox = null,
    compactMode = false,
    allowDownload = true,
    onDownloadFile,
}: FilePreviewProps) {
    const localize = useLocalize();
    const viewerType = getViewerType(fileType);
    const hasSidebar = !compactMode && supportsSidebar(viewerType);
    const hasPagination = !compactMode && supportsPagination(viewerType);
    const hasZoom = !compactMode && supportsZoom(viewerType);

    // --- PDF-specific state ---
    const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [totalPages, setTotalPages] = useState(0);
    const [targetPage, setTargetPage] = useState<number | null>(null);

    // --- Shared state ---
    const [zoomLevel, setZoomLevel] = useState(100);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Load PDF
    useEffect(() => {
        if (viewerType !== "pdf" || !fileUrl) return;

        pdfjsLib.GlobalWorkerOptions.workerSrc =
            // @ts-ignore
            __APP_ENV__.BASE_URL + "/pdf.worker.min.js";

        pdfjsLib
            .getDocument(fileUrl)
            .promise.then((doc) => {
                setPdfDoc(doc);
                setTotalPages(doc.numPages);
            })
            .catch((e) => {
                console.error("Failed to load PDF:", e);
                setError(localize("com_knowledge.load_pdf_failed"));
            });
    }, [fileUrl, viewerType]);

    // Update document title
    useEffect(() => {
        document.title = fileName;
    }, [fileName]);

    const handleZoomIn = useCallback(() => {
        setZoomLevel((prev) => Math.min(500, prev + 25));
    }, []);

    const handleZoomOut = useCallback(() => {
        setZoomLevel((prev) => Math.max(25, prev - 25));
    }, []);

    const handlePageChange = useCallback((page: number) => {
        setCurrentPage(page);
        setTargetPage(page);
    }, []);

    const handleCurrentPageChange = useCallback((page: number) => {
        setCurrentPage(page);
    }, []);

    const handleSidebarPageClick = useCallback((page: number) => {
        setCurrentPage(page);
        setTargetPage(page);
    }, []);

    const handleDownload = useCallback(() => {
        if (onDownloadFile) {
            onDownloadFile();
            return;
        }
        const link = document.createElement("a");
        link.href = fileUrl;
        link.download = fileName;
        link.target = "_blank";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }, [fileName, fileUrl, onDownloadFile]);

    const topBarDownload = allowDownload ? handleDownload : undefined;

    // Unsupported format
    if (viewerType === "unsupported") {
        return (
            <div className="w-full h-full flex flex-col">
                {!compactMode && <TopBar fileName={fileName} onDownload={topBarDownload} actions={actions} showZoom={false} />}
                <div className="flex-1 flex items-center justify-center bg-[#fbfbfb]">
                    <div className="flex flex-col items-center gap-4 text-[#86909c]">
                        <div className="text-5xl">📄</div>
                        <p className="text-lg">{localize("com_knowledge.unsupported_format_prefix")}{fileType}{localize("com_knowledge.unsupported_format_suffix")}</p>
                        {allowDownload && (
                            <button
                                onClick={handleDownload}
                                className="px-4 py-2 bg-primary text-white rounded-md text-sm hover:bg-primary/90 transition-colors"
                            >
                                {localize("com_knowledge.download_file")}</button>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    // PPTX conversion failed — show zoom controls but display error in content area
    if (conversionFailed) {
        return (
            <div className="w-full h-full flex flex-col">
                {!compactMode && (
                    <TopBar
                        fileName={fileName}
                        showZoom={true}
                        zoomLevel={zoomLevel}
                        onZoomIn={handleZoomIn}
                        onZoomOut={handleZoomOut}
                        onDownload={fileUrl ? topBarDownload : undefined}
                        actions={actions}
                    />
                )}
                <div className="flex-1 flex items-center justify-center bg-[#fbfbfb]">
                    <div className="flex flex-col items-center gap-3 text-[#86909c]">
                        <div className="text-5xl">📄</div>
                        <p className="text-base">{localize("com_knowledge.load_doc_failed")}</p>
                    </div>
                </div>
            </div>
        );
    }

    // Error state
    if (error) {
        return (
            <div className="w-full h-full flex flex-col">
                {!compactMode && <TopBar fileName={fileName} onDownload={topBarDownload} actions={actions} showZoom={false} />}
                <div className="flex-1 flex items-center justify-center bg-[#fbfbfb]">
                    <div className="flex flex-col items-center gap-3 text-[#86909c]">
                        <div className="text-4xl">📄</div>
                        <p>{error}</p>
                    </div>
                </div>
            </div>
        );
    }

    // Render the appropriate viewer
    const renderViewer = () => {
        switch (viewerType) {
            case "pdf":
                return (
                    <PdfViewer
                        pdfDoc={pdfDoc}
                        zoomLevel={zoomLevel}
                        targetPage={targetPage}
                        highlightBboxes={highlightBboxes}
                        targetBBox={targetBBox}
                        onCurrentPageChange={handleCurrentPageChange}
                    />
                );
            case "docx":
                return <DocxViewer fileUrl={fileUrl} zoomLevel={zoomLevel} />;
            case "xlsx":
                return <XlsxViewer fileUrl={fileUrl} fileExt={fileType} zoomLevel={zoomLevel} />;
            case "markdown":
                return <MarkdownViewer fileUrl={fileUrl} zoomLevel={zoomLevel} />;
            case "html":
                return <HtmlViewer fileUrl={fileUrl} zoomLevel={zoomLevel} />;
            case "image":
                return <ImageViewer fileUrl={fileUrl} zoomLevel={zoomLevel} />;
            case "text":
                return <TextViewer fileUrl={fileUrl} zoomLevel={zoomLevel} />;
            default:
                return null;
        }
    };

    return (
        <div className="w-full h-full flex flex-col overflow-hidden">
            {!compactMode && (
                <TopBar
                    fileName={fileName}
                    showSidebar={hasSidebar}
                    sidebarOpen={sidebarOpen}
                    onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
                    showZoom={hasZoom}
                    zoomLevel={zoomLevel}
                    onZoomIn={handleZoomIn}
                    onZoomOut={handleZoomOut}
                    showPagination={hasPagination}
                    currentPage={currentPage}
                    totalPages={totalPages}
                    onPageChange={handlePageChange}
                    onDownload={topBarDownload}
                    actions={actions}
                />
            )}
            <div className="flex flex-1 min-h-0">
                {hasSidebar && (
                    <Sidebar
                        open={sidebarOpen}
                        pdfDoc={pdfDoc}
                        currentPage={currentPage}
                        onPageClick={handleSidebarPageClick}
                    />
                )}
                {renderViewer()}
            </div>
        </div>
    );
}
