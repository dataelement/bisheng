import { useLocalize } from "~/hooks";
import {
    ArrowUp,
    Copy,
    Download,
    X,
    ZoomIn,
    ZoomOut
} from "lucide-react";

import { useEffect, useRef, useState } from "react";
import { Article } from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { AddSpaceIcon, AiChatIcon, FullScreenIcon, OriginalWebIcon, ShareOutlineIcon } from "~/components/icons";
import { useToastContext } from "~/Providers";
import { formatTime } from "~/utils";
import { useArticleShare } from "../hooks/useArticleShare";
import { AddToKnowledgeModal } from "./AddToKnowledgeModal";
import { useAuthContext } from "~/hooks/AuthContext";

interface ArticleDetailProps {
    article: Article;
    loading?: boolean;
    screenFull?: boolean;
    aiAssistantOpen?: boolean;
    showFullScreenBtn?: boolean;
    onFullScreen?: () => void;
    onExitAiAssistant?: () => void;
    onAiAssistant?: () => void;
}

export function ArticleDetail({ article, loading = false, screenFull = false, showFullScreenBtn = true, aiAssistantOpen = false, onFullScreen, onExitAiAssistant, onAiAssistant }: ArticleDetailProps) {
    const localize = useLocalize();
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [scale, setScale] = useState(1);
    const [showBackTop, setShowBackTop] = useState(false);
    const [showKnowledgeModal, setShowKnowledgeModal] = useState(false);
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const { handleShare } = useArticleShare();
    const { showToast } = useToastContext();

    // 使用文章的真实 HTML 内容
    const articleHtml = article.content_html || article.content || '';

    const processedHtml = `
    <html>
      <head>
        <style>
          html{scrollbar-width: none; background: #fff !important;}
          body { font-family: sans-serif; line-height: 1.6; color: #333; padding: 20px; scroll-behavior: smooth; background: #fff !important; }
          img { max-width: 100%; cursor: zoom-in; }
        </style>
      </head>
      <body>
        ${articleHtml}
       <script>
          // Unwrap images from <a> tags: replace the <a> with its child <img>
          // so clicking an image triggers the preview overlay, not a link navigation.
          document.querySelectorAll('a').forEach(a => {
            const img = a.querySelector('img');
            if (img) {
              a.replaceWith(img);
            } else {
              // Regular links: open in new tab
              a.setAttribute('target', '_blank');
              a.setAttribute('rel', 'noopener noreferrer');
            }
          });

          // Image click → preview
          document.querySelectorAll('img').forEach(img => {
            img.onclick = (e) => {
              e.stopPropagation();
              window.parent.postMessage({ type: 'IMAGE_PREVIEW', url: e.target.src }, '*');
            };
          });

          // Scroll listener: inform parent whether to show "Back to Top"
          window.onscroll = () => {
            const shouldShow = window.pageYOffset > window.innerHeight;
            window.parent.postMessage({ type: 'SCROLL_STATUS', show: shouldShow }, '*');
          };

          // Receive parent command: scroll back to top
          window.addEventListener('message', (e) => {
            if (e.data.type === 'DO_SCROLL_TOP') window.scrollTo({ top: 0, behavior: 'smooth' });
          });
        </script>
      </body>
    </html>
  `;

    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            if (event.data.type === 'IMAGE_PREVIEW') {
                setPreviewUrl(event.data.url);
                setScale(1); // Reset scale
            }
            if (event.data.type === 'SCROLL_STATUS') {
                setShowBackTop(event.data.show);
            }
        };
        window.addEventListener("message", handleMessage);
        return () => window.removeEventListener("message", handleMessage);
    }, []);

    // Helper: draw the preview image onto a canvas and return a PNG blob.
    // This bypasses CORS issues since the image is loaded via <img> with crossOrigin.
    const getImageBlob = (): Promise<Blob> => {
        return new Promise((resolve, reject) => {
            if (!previewUrl) return reject(new Error('no url'));
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                const ctx = canvas.getContext('2d');
                if (!ctx) return reject(new Error('no canvas context'));
                ctx.drawImage(img, 0, 0);
                canvas.toBlob(blob => {
                    if (blob) resolve(blob);
                    else reject(new Error('toBlob failed'));
                }, 'image/png');
            };
            img.onerror = () => reject(new Error('img load failed'));
            img.src = previewUrl;
        });
    };

    // --- Image operation logic ---
    const handleDownload = async () => {
        if (!previewUrl) return;
        try {
            const blob = await getImageBlob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `image-${Date.now()}.png`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        } catch {
            // Fallback: try fetch-based download
            try {
                const res = await fetch(previewUrl);
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `image-${Date.now()}.png`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
            } catch {
                window.open(previewUrl, '_blank');
            }
        }
    };


    const handleCopy = async () => {
        if (!previewUrl) return;
        try {
            if (!navigator.clipboard) throw new Error('Clipboard API not available');
            const blob = await getImageBlob();
            await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
            showToast({ message: localize("com_subscription.image_copied"), severity: NotificationSeverity.SUCCESS });
        } catch {
            // Fallback: copy URL string via clipboard API or legacy execCommand
            try {
                if (navigator.clipboard?.writeText) {
                    await navigator.clipboard.writeText(previewUrl);
                } else {
                    const ta = document.createElement('textarea');
                    ta.value = previewUrl;
                    ta.style.position = 'fixed';
                    ta.style.opacity = '0';
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                }
                showToast({ message: localize("com_subscription.image_copy_failed_url_copied"), severity: NotificationSeverity.WARNING });
            } catch {
                showToast({ message: localize("com_subscription.copy_failed_retry"), severity: NotificationSeverity.ERROR });
            }
        }
    };

    const handleBackToTop = () => {
        iframeRef.current?.contentWindow?.postMessage({ type: 'DO_SCROLL_TOP' }, '*');
    };


    // Check if user has knowledge_space permission from web_menu
    const { user } = useAuthContext();
    const hasKnowledge = Array.isArray((user as any)?.plugins)
        ? ((user as any).plugins as string[]).includes('knowledge_space')
        : true;
    return (
        <div className={`flex px-4 py-5 flex-col h-full  ${screenFull ? '' : 'border-l border-gray-100'}`}>
            {/* Top Toolbar */}
            <div className="border-b border-black pb-4">
                <div className="flex items-start justify-between">
                    <h2 className={`font-semibold leading-relaxed flex-1 ${aiAssistantOpen ? 'pl-10' : ''}`}
                        style={{ fontFamily: '"Source Han Serif SC", "Noto Serif SC", serif' }}>
                        {article.title}
                    </h2>
                </div>

                <div className="flex items-center justify-between pt-2">
                    <div className="w-full h-6 flex items-center gap-4">
                        <button
                            onClick={() => window.open(article.url)}
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                        >
                            <OriginalWebIcon className="size-3.5" />{localize("com_subscription.original_webpage")}</button>

                        <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => handleShare(article)}
                        >
                            <ShareOutlineIcon className="size-3.5 text-[#94BFFF]" />{localize("com_subscription.share")}</button>

                        {hasKnowledge && <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => setShowKnowledgeModal(true)}
                        >
                            <AddSpaceIcon className="size-3.5" />{localize("com_subscription.add_to_knowledge_space")}</button>}

                        {(!screenFull || (showFullScreenBtn && aiAssistantOpen)) && <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => {
                                screenFull && showFullScreenBtn ? onExitAiAssistant?.() :
                                    onFullScreen?.();
                            }}
                        >
                            <FullScreenIcon className="size-3.5" />{localize("com_subscription.fullscreen")}</button>}

                        <div className="ml-auto flex gap-3 items-center">
                            {screenFull && <div className="flex items-center text-[12px]">
                                <img className="size-4 mr-1.5" src={article.sourceAvatar} alt="" />
                                <span className="text-[#212121]">{article.sourceName}</span>
                                <span className="text-[#e5e6eb] mx-2">|</span>
                                <span className="text-[#999]">{formatTime(article.publishedAt || '', true)}</span>
                            </div>}
                            {!aiAssistantOpen && <button
                                className="flex items-center gap-1 text-xs transition-colors bg-gradient-to-br from-[#335CFF] to-[#7433FF] bg-clip-text text-transparent"
                                onClick={() => onAiAssistant?.()}
                            >
                                <AiChatIcon className="size-3.5 text-primary" />{localize("com_subscription.ai_assistant")}</button>}
                        </div>
                    </div>
                </div>
            </div>

            {/* Iframe Content Area */}
            <div className="flex-1 bg-white relative">
                {loading ? (
                    <div className="flex items-center justify-center h-full text-[#86909c] text-sm">{localize("com_subscription.loading")}</div>
                ) : !articleHtml ? (
                    <div className="flex items-center justify-center h-full text-[#86909c] text-sm">{localize("com_subscription.no_content")}</div>
                ) : (
                    <iframe
                        ref={iframeRef}
                        srcDoc={processedHtml}
                        className="w-full h-full border-none"
                    />
                )}

                {/* Back to Top Button */}
                {showBackTop && (
                    <button
                        onClick={handleBackToTop}
                        className="absolute bottom-8 right-8 size-10 bg-white shadow-lg border border-[#e5e6eb] rounded-full flex items-center justify-center text-[#4e5969] hover:text-primary transition-all animate-in fade-in slide-in-from-bottom-4"
                    >
                        <ArrowUp className="size-5" />
                    </button>
                )}
            </div>

            {/* 3. Image Preview Overlay */}
            {previewUrl && (
                <div className="fixed inset-0 z-[999] bg-black/90 flex flex-col items-center justify-center">
                    {/* Top Action Bar */}
                    <div className="absolute top-0 w-full flex justify-between p-6 text-white/80">
                        <div className="flex items-center gap-6">
                            <button onClick={() => setScale(s => s + 0.2)} className="hover:text-white flex items-center gap-1">
                                <ZoomIn className="size-5" />{localize("com_subscription.zoom_in")}</button>
                            <button onClick={() => setScale(s => Math.max(0.5, s - 0.2))} className="hover:text-white flex items-center gap-1">
                                <ZoomOut className="size-5" />{localize("com_subscription.zoom_out")}</button>
                            {/* <div className="w-px h-4 bg-white/20 mx-2" /> */}
                            {/* <button onClick={handleCopy} className="hover:text-white flex items-center gap-1">
                                <Copy className="size-5" />{localize("com_subscription.copy")}</button>
                            <button onClick={handleDownload} className="hover:text-white flex items-center gap-1">
                                <Download className="size-5" />{localize("com_subscription.download")}</button> */}
                        </div>
                        <button onClick={() => setPreviewUrl(null)} className="hover:text-white text-white bg-white/10 p-2 rounded-full">
                            <X className="size-8" />
                        </button>
                    </div>

                    {/* Image Body */}
                    <div className="overflow-auto max-w-full max-h-full flex items-center justify-center p-10 cursor-grab active:cursor-grabbing">
                        <img
                            src={previewUrl}
                            style={{ transform: `scale(${scale})`, transition: 'transform 0.2s cubic-bezier(0.4, 0, 0.2, 1)' }}
                            className="max-w-[85vw] max-h-[85vh] object-contain shadow-2xl"
                            alt="Preview"
                        />
                    </div>
                </div>
            )}

            {/* Add to Knowledge Space Modal */}
            <AddToKnowledgeModal
                open={showKnowledgeModal}
                onOpenChange={setShowKnowledgeModal}
                articleId={article.id}
            />
        </div>
    );
}