import { useTranslation } from 'react-i18next';

interface Props {
    liked?: number;
    comment?: string;
}

export default function MessageFeedback({ liked, comment }: Props) {
    const { t } = useTranslation();
    if (!liked && !comment) return null;
    return (
        <div className="mt-3 rounded-lg border border-border bg-muted/30 p-3 text-sm">
            <div className="text-muted-foreground">
                {t('log.userRating')}：{t(liked === 1 ? 'log.likeFeedback' : liked === 2 ? 'log.dislikeFeedback' : 'log.unratedFeedback')}
            </div>
            {comment && <div className="mt-2 whitespace-pre-wrap break-words text-foreground">
                {t('log.userFeedback')}：{comment}
            </div>}
        </div>
    );
}
