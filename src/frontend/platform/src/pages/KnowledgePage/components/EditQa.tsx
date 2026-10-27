import { Button, Input, Textarea, toast } from '@bisheng/ui';
import { Dialog,DialogClose,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { Outlined } from "bisheng-icons";
import type { ChangeEvent } from 'react';
import { forwardRef,useImperativeHandle,useRef,useState } from "react";
import { useTranslation } from "react-i18next";

import { InputList } from '@/components/bs-comp/formFields/InputList';
import { generateSimilarQa,getQaDetail,updateQa } from "../../../controllers/API";
import { showApiError } from "../../../controllers/request";
export interface EditQaHandle {
    open: () => void
    edit: (item: { id: string | number; source?: string | number }) => void
}
interface EditQaProps {
    knowlageId?: string
    onChange: () => void
}
const defaultQa = {
    question: '',
    similarQuestions: [''],
    answer: ''
}
export const EditQa = forwardRef<EditQaHandle, EditQaProps>(function EditQa({ knowlageId, onChange }, ref) {
    const { t } = useTranslation('knowledge');
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({ ...defaultQa });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState({
        question: false,
        answer: false
    });

    const idRef = useRef<string | number>('');
    const sourceRef = useRef<string | number>('');
    useImperativeHandle(ref, () => ({
        open() {
            setOpen(true);
        },
        edit(item: { id: string | number; source?: string | number }) {
            const { id, source } = item;
            idRef.current = id;
            sourceRef.current = source ?? '';
            setOpen(true);

            getQaDetail(id).then(response => {
                const res = response as unknown as { questions: string[]; answers: string };
                const { questions, answers } = res;
                const [question, ...similarQuestions] = questions;
                setForm({
                    question,
                    similarQuestions: [...similarQuestions, ''],
                    answer: answers
                });
            });
        }
    }));

    const handleInputChange = (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        const { name, value } = e.target;
        setForm((prevForm) => ({
            ...prevForm,
            [name]: value
        }));
    };

    const handleSimilarQuestionsChange = (list: (string | { value: string })[]) => {
        setForm((prevForm) => ({
            ...prevForm,
            similarQuestions: list.map(item => typeof item === 'string' ? item : item.value)
        }));
    };
    const handleModelGenerate = async () => {
        if (!form.question) {
            return toast.show({ type: 'warning', message: String(t('pleaseEnterQuestion') ?? '') });
        }
        setLoading(true);
        generateSimilarQa(form.question, form.answer).then(res => {
            setForm((prevForm) => {
                const updatedSimilarQuestions = [...prevForm.similarQuestions];
                updatedSimilarQuestions.splice(updatedSimilarQuestions.length - 1, 0, ...(res as unknown as { questions: string[] }).questions);
                return {
                    ...prevForm,
                    similarQuestions: updatedSimilarQuestions
                };
            });
        }).catch(showApiError).finally(() => setLoading(false));
    };


    const [saveLoad, setSaveLoad] = useState(false);
    const handleSubmit = async () => {
        const isQuestionEmpty = !form.question.trim();
        const isAnswerEmpty = !form.answer.trim();

        if (isQuestionEmpty || isAnswerEmpty) {
            setError({
                question: isQuestionEmpty,
                answer: isAnswerEmpty
            });

            return toast.show({ type: 'warning', message: String(t('questionAndAnswerCannotBeEmpty') ?? '') });
        }

        const _similarQuestions = form.similarQuestions.filter((question) => question.trim() !== '');
        if (_similarQuestions.some((q) => q.length > 100)) {
            return toast.show({ type: 'warning', message: String(t('max100CharactersForSimilarQuestion') ?? '') });
        }
        if (form.answer.length > 10000) {
            return toast.show({ type: 'warning', message: String(t('max1000CharactersForAnswer') ?? '') });
        }

        setSaveLoad(true);
        try {
        await updateQa(idRef.current, {
            questions: [form.question, ..._similarQuestions],
            answers: [form.answer],
            knowledge_id: knowlageId,
            source: sourceRef.current || 1
        });

        onChange();
        close();
        } catch (error) {
            showApiError(error);
        } finally {
            setSaveLoad(false);
        }
    };

    const close = () => {
        idRef.current = '';
        sourceRef.current = '';
        setForm({ ...defaultQa });
        setOpen(false);
        setError({
            question: false,
            answer: false
        });
    };

    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{idRef.current ? t('updateQa') : t('createQa')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div>
                        <label htmlFor="question" className="bisheng-label">
                            <span className="text-red-500">*</span>{t('question')}
                        </label>
                        <Input name="question" value={form.question} onChange={handleInputChange} className={`col-span-3 ${error.question && 'border-red-400'}`} />
                    </div>
                    <div>
                        <label htmlFor="similarQuestions" className="bisheng-label">{t('similarQuestions')}</label>
                        <InputList
                            className="max-h-60 overflow-y-auto"
                            value={form.similarQuestions}
                            onChange={handleSimilarQuestionsChange}
                        />
                        <Button className="mt-2" size="small" onClick={handleModelGenerate} disabled={loading}>
                            {loading && <Outlined.Loading  className="size-4 animate-spin"/>} {t('aiGenerate')}
                        </Button>
                    </div>
                    <div>
                        <label htmlFor="answer" className="bisheng-label">
                            <span className="text-red-500">*</span>{t('answer')}
                        </label>
                        <Textarea name="answer" value={form.answer} onChange={handleInputChange} textareaClassName={`col-span-3 h-36 ${error.answer && 'border-red-400'}`} />
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outlined" type="button" onClick={close} color="default">
                            {t('cancel2')}
                        </Button>
                    </DialogClose>
                    <Button loading={saveLoad} type="submit" onClick={handleSubmit} disabled={Boolean(saveLoad)}>
                        {t('confirm')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});
