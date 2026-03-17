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
import { AddSpaceIcon, AiChatIcon, FullScreenIcon, OriginalWebIcon, ShareOutlineIcon } from "~/components/icons";
import { useToastContext } from "~/Providers";
import { formatTime } from "~/utils";
import { useArticleShare } from "../hooks/useArticleShare";
import { AddToKnowledgeModal } from "./AddToKnowledgeModal";

interface ArticleDetailProps {
    article: Article;
    loading?: boolean;
    screenFull?: boolean;
    aiAssistantOpen?: boolean;
    onFullScreen?: () => void;
    onExitAiAssistant?: () => void;
    onAiAssistant?: () => void;
}

export function ArticleDetail({ article, loading = false, screenFull = false, aiAssistantOpen = false, onFullScreen, onExitAiAssistant, onAiAssistant }: ArticleDetailProps) {
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [scale, setScale] = useState(1);
    const [showBackTop, setShowBackTop] = useState(false);
    const [showKnowledgeModal, setShowKnowledgeModal] = useState(false);
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const { handleShare } = useArticleShare();

    // 使用文章的真实 HTML 内容
    const articleHtml = article.content_html || article.content || '';

    const processedHtml = `
    <html>
      <head>
        <style>
          html{scrollbar-width: none;}
          body { font-family: sans-serif; line-height: 1.6; color: #333; padding: 20px; scroll-behavior: smooth; }
          img { max-width: 100%; cursor: zoom-in; }
        </style>
      </head>
      <body>
        ${articleHtml}
       <script>
          // Image click
          document.querySelectorAll('img').forEach(img => {
            img.onclick = (e) => window.parent.postMessage({ type: 'IMAGE_PREVIEW', url: e.target.src }, '*');
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

    // --- Image operation logic ---
    const handleDownload = async () => {
        if (!previewUrl) return;
        const res = await fetch(previewUrl);
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `image-${Date.now()}.png`;
        a.click();
    };

    const handleCopy = async () => {
        if (!previewUrl) return;
        try {
            const data = await fetch(previewUrl);
            const blob = await data.blob();
            await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
            alert("Image copied to clipboard");
        } catch (err) {
            console.log('err :>> ', err);
            // Fallback: copy link only
            await navigator.clipboard.writeText(previewUrl);
            alert("Failed to copy image, copied link instead");
        }
    };

    const handleBackToTop = () => {
        iframeRef.current?.contentWindow?.postMessage({ type: 'DO_SCROLL_TOP' }, '*');
    };


    const hasKnowledge = true
    return (
        <div className={`flex px-4 py-5 flex-col h-full  ${screenFull ? '' : 'border-l border-gray-100'}`}>
            {/* Top Toolbar */}
            <div className="border-b border-black pb-4">
                <div className="flex items-start justify-between">
                    <h2 className={`font-semibold leading-relaxed flex-1 font-[serif] ${aiAssistantOpen ? 'pl-10' : ''}`}>
                        {article.title}
                    </h2>
                </div>

                <div className="flex items-center justify-between pt-2">
                    <div className="w-full h-6 flex items-center gap-4">
                        <button
                            onClick={() => window.open(article.url)}
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                        >
                            <OriginalWebIcon className="size-3.5" />
                            原网页
                        </button>

                        <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => handleShare(article)}
                        >
                            <ShareOutlineIcon className="size-3.5 text-[#94BFFF]" />
                            分享
                        </button>

                        {hasKnowledge && <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => setShowKnowledgeModal(true)}
                        >
                            <AddSpaceIcon className="size-3.5" />
                            加入知识空间
                        </button>}

                        {!(screenFull || aiAssistantOpen) && <button
                            className="flex items-center gap-1 text-xs transition-colors text-gray-900"
                            onClick={() => {
                                onFullScreen?.();
                            }}
                        >
                            <FullScreenIcon className="size-3.5" />
                            全屏
                        </button>}

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
                                <AiChatIcon className="size-3.5 text-primary" />
                                AI 助手
                            </button>}
                        </div>
                    </div>
                </div>
            </div>

            {/* Iframe Content Area */}
            <div className="flex-1 bg-white relative">
                {loading ? (
                    <div className="flex items-center justify-center h-full text-[#86909c] text-sm">加载中...</div>
                ) : !articleHtml ? (
                    <div className="flex items-center justify-center h-full text-[#86909c] text-sm">暂无内容</div>
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
                                <ZoomIn className="size-5" /> 放大
                            </button>
                            <button onClick={() => setScale(s => Math.max(0.5, s - 0.2))} className="hover:text-white flex items-center gap-1">
                                <ZoomOut className="size-5" /> 缩小
                            </button>
                            <div className="w-px h-4 bg-white/20 mx-2" />
                            <button onClick={handleCopy} className="hover:text-white flex items-center gap-1">
                                <Copy className="size-5" /> 复制
                            </button>
                            <button onClick={handleDownload} className="hover:text-white flex items-center gap-1">
                                <Download className="size-5" /> 下载
                            </button>
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
            />
        </div>
    );
}