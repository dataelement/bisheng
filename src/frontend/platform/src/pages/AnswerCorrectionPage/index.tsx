import { Button, Textarea } from "@bisheng/ui";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import request from "@/controllers/request";

const root = "/api/v1/answer-corrections/";
type View = "owner" | "assigned";
type State = "pending_assignment" | "pending_processing" | "pending_reply" | "replied";
interface Feedback {
    id: number;
    quote: string;
    correction: string;
    evidence: string;
    state: State;
    result: string | null;
    reply: string | null;
}
interface Page<T> {
    items: T[];
    total: number;
}
interface Option {
    id: number;
    name: string;
}
interface FeedbackDialogProps {
    feedback: Feedback;
    view: View;
    onClose: () => void;
    onRefresh: () => void;
}

function useFeedbackRequest<T>(url: string | null, refresh = 0) {
    const [response, setResponse] = useState<{ url: string; data?: T; error?: boolean }>();
    useEffect(() => {
        if (!url) return;
        const controller = new AbortController();
        void request.get<unknown, T>(url, { signal: controller.signal }).then(
            (data) => { if (!controller.signal.aborted) setResponse({ url, data }); },
            () => { if (!controller.signal.aborted) setResponse({ url, error: true }); },
        );
        return () => controller.abort();
    }, [url, refresh]);
    const current = url === response?.url ? response : undefined;
    return { data: current?.data, isError: current?.error, isLoading: Boolean(url && !current) };
}

function FeedbackDialog({ feedback, view, onClose, onRefresh }: FeedbackDialogProps) {
    const { t } = useTranslation();
    const [knowledgeId, setKnowledgeId] = useState("");
    const [assigneeId, setAssigneeId] = useState("");
    const [candidatePage, setCandidatePage] = useState(1);
    const [text, setText] = useState("");
    const assign = view === "owner" && feedback.state === "pending_assignment";
    const reply = view === "owner" && feedback.state === "pending_reply";
    const process = view === "assigned" && feedback.state === "pending_processing";
    const path = `${root}${feedback.id}`;
    const knowledge = useFeedbackRequest<{ items: Option[] }>(assign ? `${path}/knowledge-options` : null);
    const candidates = useFeedbackRequest<Page<Option>>(assign && knowledgeId
        ? `${path}/assignee-options?knowledge_id=${knowledgeId}&page=${candidatePage}`
        : null);
    const [submitting, setSubmitting] = useState(false);
    const [failed, setFailed] = useState(false);
    const handleSave = async () => {
        setSubmitting(true);
        setFailed(false);
        try {
            if (assign) {
                await request.post(`${path}/assignment`, {
                    knowledge_id: Number(knowledgeId), assignee_id: Number(assigneeId),
                });
            } else if (reply) {
                await request.post(`${path}/reply`, { reply: text.trim() });
            } else {
                await request.post(`${path}/result`, { result: text.trim() });
            }
            onClose();
        } catch {
            setFailed(true);
        } finally {
            setSubmitting(false);
            onRefresh();
        }
    };

    return (
        <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
            <DialogContent className="max-h-[85vh] overflow-y-auto">
                <DialogHeader><DialogTitle>{t("answerCorrection.title")}</DialogTitle></DialogHeader>
                <dl className="space-y-3 whitespace-pre-wrap break-words">
                    <div><dt>{t("answerCorrection.quote")}</dt><dd>{feedback.quote}</dd></div>
                    <div><dt>{t("answerCorrection.correction")}</dt><dd>{feedback.correction}</dd></div>
                    <div><dt>{t("answerCorrection.evidence")}</dt><dd>{feedback.evidence}</dd></div>
                    {feedback.result && <div><dt>{t("answerCorrection.result")}</dt><dd>{feedback.result}</dd></div>}
                    {feedback.reply && <div><dt>{t("answerCorrection.reply")}</dt><dd>{feedback.reply}</dd></div>}
                </dl>
                {assign && (
                    <div className="space-y-3">
                        <label className="block">
                            {t("answerCorrection.knowledge")}
                            <select className="block w-full" value={knowledgeId} onChange={(event) => {
                                setKnowledgeId(event.target.value);
                                setAssigneeId("");
                                setCandidatePage(1);
                            }}>
                                <option value="">{t("answerCorrection.choose")}</option>
                                {knowledge.data?.items.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
                            </select>
                        </label>
                        <label className="block">
                            {t("answerCorrection.assignee")}
                            <select className="block w-full" value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}>
                                <option value="">{t("answerCorrection.choose")}</option>
                                {candidates.data?.items.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
                            </select>
                        </label>
                        {knowledgeId && <Pagination page={candidatePage} total={candidates.data?.total ?? 0}
                            onPage={(page) => { setCandidatePage(page); setAssigneeId(""); }} />}
                    </div>
                )}
                {(process || reply) && <label className="block">
                    {t(reply ? "answerCorrection.reply" : "answerCorrection.result")}
                    <Textarea value={text} onChange={(event) => setText(event.target.value)} />
                </label>}
                {(failed || knowledge.isError || candidates.isError) &&
                    <p role="alert">{t("answerCorrection.error")}</p>}
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>{t("answerCorrection.close")}</Button>
                    {(assign || process || reply) && <Button
                        disabled={submitting || (assign ? !knowledgeId || !assigneeId : !text.trim())}
                        onClick={handleSave}
                    >
                        {t(assign ? "answerCorrection.assign" : reply ? "answerCorrection.send" : "answerCorrection.save")}
                    </Button>}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

interface PaginationProps {
    page: number;
    total: number;
    onPage: (page: number) => void;
}

function Pagination({ page, total, onPage }: PaginationProps) {
    const { t } = useTranslation();
    return (
        <div className="flex gap-2">
            <Button variant="outline" disabled={page === 1} onClick={() => onPage(page - 1)}>
                {t("answerCorrection.previous")}
            </Button>
            <Button variant="outline" disabled={page * 20 >= total} onClick={() => onPage(page + 1)}>
                {t("answerCorrection.next")}
            </Button>
        </div>
    );
}

export function AnswerCorrectionPage() {
    const { t } = useTranslation();
    const [view, setView] = useState<View>("owner");
    const [page, setPage] = useState(1);
    const [feedbackId, setFeedbackId] = useState<number | null>(null);
    const [refresh, setRefresh] = useState(0);
    const queue = useFeedbackRequest<Page<Feedback>>(`${root}?view=${view}&page=${page}`, refresh);
    const active = queue.data?.items.find((item) => item.id === feedbackId);
    return (
        <section className="space-y-4 p-6">
            <h1 className="text-lg font-semibold">{t("answerCorrection.title")}</h1>
            <div className="flex gap-2">
                {(["owner", "assigned"] as const).map((option) => <Button key={option}
                    variant={view === option ? "default" : "outline"}
                    aria-pressed={view === option}
                    onClick={() => { setView(option); setPage(1); setFeedbackId(null); }}>
                    {t(`answerCorrection.${option}`)}
                </Button>)}
            </div>
            {queue.isLoading && <p role="status">{t("answerCorrection.loading")}</p>}
            {queue.isError && <p role="alert">{t("answerCorrection.error")}</p>}
            {queue.data?.total === 0 && <p>{t("answerCorrection.empty")}</p>}
            <ul className="space-y-2">
                {queue.data?.items.map((item) => <li key={item.id} className="flex items-center justify-between gap-4 border-b py-2">
                    <span className="min-w-0 truncate">{item.quote}</span>
                    <span>{t(`answerCorrection.${item.state}`)}</span>
                    <Button variant="outline" onClick={() => setFeedbackId(item.id)}>{t("answerCorrection.open")}</Button>
                </li>)}
            </ul>
            <Pagination page={page} total={queue.data?.total ?? 0} onPage={setPage} />
            {active && <FeedbackDialog key={active.id} feedback={active} view={view} onClose={() => setFeedbackId(null)} onRefresh={() => setRefresh((value) => value + 1)} />}
        </section>
    );
}
