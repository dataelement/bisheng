import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { MessageSquareText } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import MessageFeedback from './MessageFeedback';

interface Props {
    count?: number;
    comments?: { message_id: number; comment: string; liked: number }[];
}

export default function AuditFeedbackButton({ count = 0, comments = [] }: Props) {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    return <>
        <button
            type="button"
            aria-label={t('log.feedbackOpinions')}
            title={t('log.feedbackOpinions')}
            className="flex flex-col items-center text-xs rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            onClick={() => setOpen(true)}
        >
            <MessageSquareText size={20} className={count ? 'text-primary' : 'text-gray-400'} />
            <span>{count}</span>
        </button>
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="w-[calc(100vw-32px)] max-w-xl" aria-describedby={undefined}>
                <DialogHeader><DialogTitle>{t('log.feedbackOpinions')}</DialogTitle></DialogHeader>
                <div className="max-h-[60vh] overflow-y-auto">
                    {comments.length
                        ? comments.map(item => <MessageFeedback key={item.message_id} liked={item.liked} comment={item.comment} />)
                        : <p className="py-6 text-center text-sm text-muted-foreground">{t('log.noFeedback')}</p>}
                </div>
            </DialogContent>
        </Dialog>
    </>;
}
