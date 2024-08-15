import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge";
import { LoadIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogFooter, DialogHeader, Dialog, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, InputList, Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { generateSimilarQa, updateQa } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";

const DEFAULT_FORM = {
    knowledgeLib: [],
    question: '',
    similarQuestions: [''],
    answer: ''
};

const SaveQaLibForm = forwardRef(({ }, ref) => {
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({ ...DEFAULT_FORM });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState({
        knowledgeLib: false,
        question: false,
        answer: false
    });

    const idRef = useRef('');

    useImperativeHandle(ref, () => ({
        open(id, qa) {
            idRef.current = id;
            setOpen(true);
            const { q, a } = qa;
            setForm({
                knowledgeLib: [],
                question: q,
                similarQuestions: [''],
                answer: a
            });
        }
    }));

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setForm((prevForm) => ({
            ...prevForm,
            [name]: value
        }));
    };

    const handleSimilarQuestionsChange = (list) => {
        setForm((prevForm) => ({
            ...prevForm,
            similarQuestions: list
        }));
    };

    const handleKnowledgeLibChange = (value) => {
        setForm((prevForm) => ({
            ...prevForm,
            knowledgeLib: value
        }));
    };

    const handleModelGenerate = async () => {

        if (!form.question) return message({
            variant: 'warning',
            description: '请先输入问题'
        })
        setLoading(true);
        captureAndAlertRequestErrorHoc(generateSimilarQa(form.question, form.answer).then(res => {
            setForm((prevForm) => {
                const updatedSimilarQuestions = [...prevForm.similarQuestions];
                updatedSimilarQuestions.splice(updatedSimilarQuestions.length - 1, 0, ...res.questions);
                return {
                    ...prevForm,
                    similarQuestions: updatedSimilarQuestions
                };
            });
            setLoading(false);
        }))
    };

    const { message } = useToast();
    const handleSubmit = async () => {
        const isKnowledgeLibEmpty = form.knowledgeLib.length === 0;
        const isQuestionEmpty = !form.question.trim();
        const isAnswerEmpty = !form.answer.trim();

        if (isKnowledgeLibEmpty || isQuestionEmpty || isAnswerEmpty) {
            setError({
                knowledgeLib: isKnowledgeLibEmpty,
                question: isQuestionEmpty,
                answer: isAnswerEmpty
            });

            return message({
                variant: 'warning',
                description: 'QA知识库、问题、答案不能为空'
            });
        }

        const _similarQuestions = form.similarQuestions.filter((question) => question.trim() !== '');
        if (_similarQuestions.some((q) => q.length > 100)) return message({
            variant: 'warning',
            description: '相似问最多100个字'
        });
        if (form.answer.length > 1000) return message({
            variant: 'warning',
            description: '答案最多1000个字'
        });

        captureAndAlertRequestErrorHoc(updateQa('', {
            questions: [form.question, ..._similarQuestions],
            answers: [form.answer],
            knowledge_id: form.knowledgeLib[0].value,
            source: 2
        }).then(res => {
            message({
                variant: 'success',
                description: '存储成功'
            });
        }))
        close();
    };

    const close = () => {
        idRef.current = '';
        setForm({ ...DEFAULT_FORM });
        setOpen(false);
        setError({
            knowledgeLib: false,
            question: false,
            answer: false
        });
    };

    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>添加新的QA到QA知识库</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div>
                        <label htmlFor="knowledgeLib" className="bisheng-label"><span className="text-red-500">*</span>QA知识库</label>
                        <KnowledgeSelect
                            type="qa"
                            value={form.knowledgeLib}
                            onChange={handleKnowledgeLibChange}
                            className={`${error.knowledgeLib && 'border-red-400'}`}
                        />
                    </div>
                    <div>
                        <label htmlFor="question" className="bisheng-label"><span className="text-red-500">*</span>问题</label>
                        <Input name="question" className={`col-span-3 ${error.question && 'border-red-400'}`} value={form.question} onChange={handleInputChange} />
                    </div>
                    <div>
                        <label htmlFor="similarQuestions" className="bisheng-label">相似问</label>
                        <div className="max-h-52 overflow-y-auto">
                            <InputList
                                value={form.similarQuestions}
                                onChange={handleSimilarQuestionsChange}
                            />
                        </div>
                        <Button className="mt-2" size="sm" onClick={handleModelGenerate} disabled={loading}>
                            {loading && <LoadIcon />}模型生成
                        </Button>
                    </div>
                    <div>
                        <label htmlFor="answer" className="bisheng-label"><span className="text-red-500">*</span>答案</label>
                        <Textarea name="answer" className={`col-span-3 min-h-36 ${error.answer && 'border-red-400'}`} value={form.answer} onChange={handleInputChange} />
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={close}>取消</Button>
                    </DialogClose>
                    <Button type="submit" className="px-11" onClick={handleSubmit}>确认</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

export default SaveQaLibForm;
