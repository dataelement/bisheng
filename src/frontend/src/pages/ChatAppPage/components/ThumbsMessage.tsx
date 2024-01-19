
import { Textarea } from "../../../components/ui/textarea";
import { Button } from "../../../components/ui/button";

import React, { useState, forwardRef, useImperativeHandle, useRef } from 'react';
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
        if (!msgRef.current.value) {
            return setError(true);
        }

        disLikeCommentApi(chatIdRef.current, msgRef.current.value)
        setOpen(false);
        setError(false);
    };

    return (
        <dialog className={`modal bg-blur-shared ${open ? 'modal-open' : 'modal-close'}`} onClick={() => setOpen(false)}>
            <div className="rounded-xl px-4 py-6 bg-[#fff] shadow-lg dark:bg-background w-[400px]" onClick={e => e.stopPropagation()}>
                <p className="mb-2">{t('chat.feedback')}</p>
                <Textarea ref={msgRef} maxLength={1024} className={`textarea ${error ? 'border border-red-400' : ''}`} ></Textarea>
                <div className="flex justify-end gap-4 mt-4">
                    <Button size="sm" variant="outline" onClick={() => setOpen(false)}>{t('cancel')}</Button>
                    <Button size="sm" onClick={handleSubmit}>{t('submit')}</Button>
                </div>
            </div>
        </dialog>
    );
});

export default ThumbsMessage;
