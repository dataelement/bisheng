
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { Textarea } from '@/components/bs-ui/input';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { forwardRef, useImperativeHandle, useRef, useState } from 'react';
import { useTranslation } from "react-i18next";
import { disLikeCommentApi } from "../../../controllers/API";

const ThumbsMessage = forwardRef((props, ref) => {
    const { t } = useTranslation()

    const [open, setOpen] = useState(false);
    const [error, setError] = useState(false);

    const msgRef = useRef(null)
    const chatIdRef = useRef(null)

    useImperativeHandle(ref, () => ({
        openModal: (chatId) => {
            setOpen(true)
            chatIdRef.current = chatId
            msgRef.current.value = ''
        }
    }));

    const { message } = useToast()
    const handleSubmit = () => {
        if (!msgRef.current.value) {
            message({
                title: t('prompt'),
                variant: 'warning',
                description: t('chat.feedbackRequired')
            });
            return setError(true);
        }

        disLikeCommentApi(chatIdRef.current, msgRef.current.value)
        setOpen(false);
        setError(false);
    };

    return <Dialog open={open} onOpenChange={setOpen} >
        <DialogContent className="sm:max-w-[425px]">
            <DialogHeader>
                <DialogTitle>{t('chat.feedback')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <p className="mb-2"></p>
                <Textarea ref={msgRef} maxLength={9999} className={`textarea ${error ? 'border border-red-400' : ''}`} ></Textarea>
                <div className="flex justify-end gap-4 mt-4">
                    <Button className='px-11' variant="outline" onClick={() => setOpen(false)}>{t('cancel')}</Button>
                    <Button className='px-11' onClick={handleSubmit}>{t('submit')}</Button>
                </div>
            </div>
        </DialogContent>
    </Dialog>
});

export default ThumbsMessage;
