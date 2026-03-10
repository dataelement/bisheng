import { useCallback } from "react";
import { Article } from "~/api/channels";
import { useToastContext } from "~/Providers";
import { copyText } from "~/utils";

export function useArticleShare() {
    const { showToast } = useToastContext();

    const handleShare = useCallback((article: Article) => {
        const shareText = `我正在阅读【${article.title}】${article.url}`;
        copyText(shareText).then(() => {
            showToast({ message: '分享链接已复制到粘贴板', status: 'success' });
        }).catch(() => {
            showToast({ message: '复制失败，请重试', status: 'error' });
        });
    }, [showToast]);

    return { handleShare };
}
