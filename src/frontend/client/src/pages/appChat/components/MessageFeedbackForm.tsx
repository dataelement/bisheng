
import { forwardRef, useImperativeHandle, useRef, useState } from 'react';
import { useTranslation } from "react-i18next";
import { disLikeCommentApi } from '~/api/apps';
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Textarea } from '~/components';
import { useToastContext } from '~/Providers';

const MessageFeedbackForm = forwardRef((props, ref) => {
    const { t } = useTranslation()

    const [open, setOpen] = useState(false);
    const [error, setError] = useState(false);

    const msgRef = useRef(null)
    const chatIdRef = useRef(null)

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
        if (!msgRef.current.value) {
            showToast({ message: '反馈信息不能为空', status: 'warning' });
            return setError(true);
        }

        disLikeCommentApi(chatIdRef.current, msgRef.current.value)
        setOpen(false);
        setError(false);
    };

    return <Dialog open={open} onOpenChange={setOpen} >
        <DialogContent className="sm:max-w-[425px]">
            <DialogHeader>
                <DialogTitle>反馈</DialogTitle>
            </DialogHeader>
            <div className="">
                <p className="mb-2"></p>
                <Textarea ref={msgRef} maxLength={9999} className={`textarea ${error ? 'border border-red-400' : ''}`} ></Textarea>
                <div className="flex justify-end gap-4 mt-4">
                    <Button className='px-11' variant="outline" onClick={() => setOpen(false)}>取消</Button>
                    <Button className='px-11' onClick={handleSubmit}>提交</Button>
                </div>
            </div>
        </DialogContent>
    </Dialog>
});

export default MessageFeedbackForm;
