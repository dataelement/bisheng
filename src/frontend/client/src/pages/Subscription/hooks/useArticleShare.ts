import { useLocalize } from "~/hooks";
import { useCallback } from "react";
import { Article } from "~/api/channels";
import { useToastContext } from "~/Providers";
import { copyText } from "~/utils";

export function useArticleShare() {
    const localize = useLocalize();
    const { showToast } = useToastContext();

    const handleShare = useCallback((article: Article) => {
        const shareText = localize("com_subscription.reading_article_share_no_dot", { title: article.title, url: article.url });
        copyText(shareText).then(() => {
            showToast({ message: localize("com_subscription.share_link_copied"), status: 'success' });
        }).catch(() => {
            showToast({ message: localize("com_subscription.copy_failed_retry"), status: 'error' });
        });
    }, [showToast]);

    return { handleShare };
}
