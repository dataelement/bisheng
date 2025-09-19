
import { forwardRef, useImperativeHandle, useRef, useState } from 'react';
import useLocalize from "~/hooks/useLocalize";
import { disLikeCommentApi } from '~/api/apps';
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Textarea } from '~/components';
import { useToastContext } from '~/Providers';

const MessageFeedbackForm = forwardRef((props, ref) => {
    const t = useLocalize()

    const [open, setOpen] = useState(false);
    const [error, setError] = useState(false);

    const msgRef = useRef<HTMLTextAreaElement | null>(null)
    const chatIdRef = useRef<string | null>(null)

    useImperativeHandle(ref, () => ({
        openModal: (chatId) => {
            setOpen(true)
            chatIdRef.current = chatId
            if (msgRef.current) {
                msgRef.current.value = ''
            }
        }
    }));

    const { showToast } = useToastContext();
    const handleSubmit = () => {
        if (!msgRef.current?.value) {
            showToast({ message: t('com_feedback_required'), status: 'warning' });
            return setError(true);
        }

        disLikeCommentApi(chatIdRef.current as string, msgRef.current.value)
        setOpen(false);
        setError(false);
    };

    return <Dialog open={open} onOpenChange={setOpen} >
        <DialogContent className="sm:max-w-[425px]">
            <DialogHeader>
                <DialogTitle>{t('com_feedback_title')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <p className="mb-2"></p>
                <Textarea ref={msgRef} maxLength={9999} className={`textarea ${error ? 'border border-red-400' : ''}`} ></Textarea>
                <div className="flex justify-end gap-4 mt-4">
                    <Button className='px-11' variant="outline" onClick={() => setOpen(false)}>{t('com_ui_cancel')}</Button>
                    <Button className='px-11' onClick={handleSubmit}>{t('com_ui_submit')}</Button>
                </div>
            </div>
        </DialogContent>
    </Dialog>
});

export default MessageFeedbackForm;
