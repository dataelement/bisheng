import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getCorrectionEligibility, listMyCorrections, submitCorrection } from "~/api/answerCorrection";
import { Button } from "~/components/ui/Button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "~/components/ui/Dialog";
import { Textarea } from "@bisheng/ui";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";

interface AnswerCorrectionButtonProps {
    messageId: string | number;
}

const fields = ["quote", "correction", "evidence"] as const;
const emptyDraft = { quote: "", correction: "", evidence: "" };

export function AnswerCorrectionButton({ messageId }: AnswerCorrectionButtonProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const answerId = Number(messageId);
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState(emptyDraft);
    const eligible = useQuery({
        queryKey: ["answer-correction-eligibility", answerId],
        queryFn: () => getCorrectionEligibility(answerId),
        enabled: Number.isSafeInteger(answerId) && answerId > 0,
        staleTime: 60_000,
        retry: false,
    });
    const submit = useMutation({
        mutationFn: submitCorrection,
        onSuccess: () => {
            setOpen(false);
            setDraft(emptyDraft);
            void queryClient.invalidateQueries({ queryKey: ["my-answer-corrections"] });
            showToast({ message: localize("com_feedback_thanks"), status: "success" });
        },
    });

    if (!eligible.data?.eligible) return null;
    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(true)}>
                {localize("com_correction_report")}
            </Button>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{localize("com_correction_report")}</DialogTitle>
                </DialogHeader>
                <form onSubmit={(event) => {
                    event.preventDefault();
                    submit.mutate({ answer_id: answerId, ...draft });
                }}>
                    {fields.map((field) => (
                        <label key={field} className="mb-3 block text-sm">
                            {localize(`com_correction_${field}`)}
                            <Textarea
                                required
                                value={draft[field]}
                                onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                            />
                        </label>
                    ))}
                    {submit.isError && <p role="alert">{localize("com_correction_error")}</p>}
                    <DialogFooter>
                        <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                            {localize("com_ui_cancel")}
                        </Button>
                        <Button type="submit" disabled={submit.isLoading || fields.some((field) => !draft[field].trim())}>
                            {localize("com_ui_submit")}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

export function MyAnswerCorrectionsButton() {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);
    const [page, setPage] = useState(1);
    const history = useQuery({
        queryKey: ["my-answer-corrections", page],
        queryFn: () => listMyCorrections(page),
        enabled: open,
    });

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(true)}>
                {localize("com_correction_mine")}
            </Button>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{localize("com_correction_mine")}</DialogTitle>
                </DialogHeader>
                <ul className="max-h-[50vh] space-y-3 overflow-auto">
                    {history.data?.items.map((item) => (
                        <li key={item.id} className="whitespace-pre-wrap break-words border-b pb-3 text-sm">
                            <p>{item.quote}</p>
                            <p>{localize(`com_correction_${item.state}`)}</p>
                            {item.reply && <p>{item.reply}</p>}
                        </li>
                    ))}
                </ul>
                {history.isError && <p role="alert">{localize("com_correction_error")}</p>}
                {history.data?.total === 0 && <p>{localize("com_correction_empty")}</p>}
                <DialogFooter>
                    <Button type="button" variant="outline" disabled={page === 1} onClick={() => setPage(page - 1)}>
                        {localize("com_correction_previous")}
                    </Button>
                    <Button type="button" variant="outline" disabled={page * 20 >= (history.data?.total ?? 0)} onClick={() => setPage(page + 1)}>
                        {localize("com_correction_next")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
