// @ts-strict-ignore
import { Button, Textarea, toast } from '@bisheng/ui';


import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';


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


    const handleSubmit = () => {
        if (!msgRef.current.value || msgRef.current.value.length > 9999) {
            toast.show({ type: 'warning', message: [String(t('prompt') ?? ''), String(t('chat.feedbackRequired') ?? '')].filter(Boolean).join('\n') });
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
                <Textarea ref={msgRef} maxLength={9999} textareaClassName={`textarea ${error ? 'border border-red-400' : ''}`} showCount></Textarea>
                <div className="flex justify-end gap-4 mt-4">
                    <Button className='px-11' variant="outlined" onClick={() => setOpen(false)} color="default">{t('cancel')}</Button>
                    <Button className='px-11' onClick={handleSubmit}>{t('submit')}</Button>
                </div>
            </div>
        </DialogContent>
    </Dialog>
});

export default ThumbsMessage;
