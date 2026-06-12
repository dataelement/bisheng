/**
 * F035 Track H (P3): intent-clarification / follow-up card (spec §2,
 * user_input event). One question per page (‹ 1/N ›): single-select /
 * multi-select / free text, with a trailing "type your own" option. Bottom
 * right "skip" skips the current question; top-right × skips the rest and
 * submits whatever was collected. All answers are merged into one structured
 * text and submitted through the existing user-input API in a single shot.
 * Unparseable payloads degrade to a plain textarea (legacy UserInput shape).
 */
import { ArrowRight, Check, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, Textarea } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import type { ClarifyQuestion, ExecStepEventData } from './stepUtils';
import { composeClarifyAnswer, parseClarifyRequest } from './stepUtils';

interface ClarifyCardProps {
    data: ExecStepEventData;
    disabled?: boolean;
    /** submit the merged answer; rides the existing user-input API upstream */
    onSubmit: (taskId: string, answer: string) => void;
}

const CUSTOM_KEY = '__custom__';

export function ClarifyCard({ data, disabled = false, onSubmit }: ClarifyCardProps) {
    const localize = useLocalize();
    const request = useMemo(() => parseClarifyRequest(data), [data]);
    const { questions } = request;

    const [page, setPage] = useState(0);
    /** question.id -> selected option texts; CUSTOM_KEY entry = free input flag */
    const [answers, setAnswers] = useState<Record<string, string[]>>({});
    const [customText, setCustomText] = useState<Record<string, string>>({});
    const [freeText, setFreeText] = useState('');
    const [submitted, setSubmitted] = useState(false);

    const skipText = localize('com_linsight_clarify_skipped');

    const finishAndSubmit = (finalAnswers: Record<string, string[]>) => {
        if (submitted) return;
        setSubmitted(true);
        // merge custom input text into each question's answer list
        const merged: Record<string, string[]> = {};
        questions.forEach((q) => {
            const list = (finalAnswers[q.id] || []).filter((v) => v !== CUSTOM_KEY);
            const custom = (finalAnswers[q.id] || []).includes(CUSTOM_KEY) ? customText[q.id]?.trim() : '';
            merged[q.id] = custom ? [...list, custom] : list;
        });
        const answerText = questions.length
            ? composeClarifyAnswer(questions, merged, skipText)
            : freeText.trim() || skipText;
        onSubmit(request.taskId, answerText);
    };

    const goNextOrSubmit = (nextAnswers: Record<string, string[]>) => {
        if (page < questions.length - 1) {
            setPage(page + 1);
        } else {
            finishAndSubmit(nextAnswers);
        }
    };

    const handleSelect = (q: ClarifyQuestion, option: string) => {
        if (disabled || submitted) return;
        setAnswers((prev) => {
            const current = prev[q.id] || [];
            let next: string[];
            if (q.multiple) {
                next = current.includes(option) ? current.filter((o) => o !== option) : [...current, option];
            } else {
                next = [option];
            }
            return { ...prev, [q.id]: next };
        });
    };

    const handleSkipCurrent = () => {
        if (disabled || submitted) return;
        if (!questions.length) return finishAndSubmit(answers);
        const next = { ...answers, [questions[page].id]: [] };
        setAnswers(next);
        goNextOrSubmit(next);
    };

    const handleClose = () => {
        // × = skip everything not answered yet and submit what we have
        if (disabled || submitted) return;
        finishAndSubmit(answers);
    };

    const handleConfirm = () => {
        if (disabled || submitted) return;
        goNextOrSubmit(answers);
    };

    const q = questions[page];
    const selected = (q && answers[q.id]) || [];
    const customSelected = selected.includes(CUSTOM_KEY);
    const hasAnswer = q
        ? selected.some((v) => v !== CUSTOM_KEY) || (customSelected && !!customText[q.id]?.trim())
        : !!freeText.trim();

    return (
        <div className="my-2 w-full rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            {/* header: guide text + pager + close */}
            <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-gray-800">
                    {request.callReason || localize('com_linsight_clarify_title')}
                </p>
                <div className="flex shrink-0 items-center gap-2">
                    {questions.length > 1 && (
                        <div className="flex items-center gap-1 text-xs text-gray-400">
                            <button
                                type="button"
                                disabled={page === 0}
                                onClick={() => setPage(page - 1)}
                                className="rounded p-0.5 hover:bg-gray-100 disabled:opacity-30"
                            >
                                <ChevronLeft size={14} />
                            </button>
                            <span>
                                {page + 1}/{questions.length}
                            </span>
                            <button
                                type="button"
                                disabled={page === questions.length - 1}
                                onClick={() => setPage(page + 1)}
                                className="rounded p-0.5 hover:bg-gray-100 disabled:opacity-30"
                            >
                                <ChevronRight size={14} />
                            </button>
                        </div>
                    )}
                    <button
                        type="button"
                        onClick={handleClose}
                        className="rounded p-0.5 text-gray-400 hover:bg-gray-100"
                        aria-label="close"
                    >
                        <X size={16} />
                    </button>
                </div>
            </div>

            {/* body: current question */}
            {q ? (
                <div className="mt-3">
                    <div className="flex items-center gap-2 text-sm text-gray-700">
                        <span>{q.question}</span>
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-400">
                            {q.multiple
                                ? localize('com_linsight_clarify_multi')
                                : localize('com_linsight_clarify_single')}
                        </span>
                    </div>
                    <ul className="mt-2 space-y-1.5">
                        {q.options.map((option, i) => {
                            const active = selected.includes(option);
                            return (
                                <li key={i}>
                                    <button
                                        type="button"
                                        disabled={disabled || submitted}
                                        onClick={() => handleSelect(q, option)}
                                        className={cn(
                                            'flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors',
                                            active
                                                ? 'border-blue-400 bg-blue-50 text-blue-700'
                                                : 'border-gray-200 text-gray-700 hover:border-blue-200 hover:bg-gray-50',
                                        )}
                                    >
                                        <span className="flex-1">
                                            {i + 1}. {option}
                                        </span>
                                        {active && <Check size={14} className="shrink-0" />}
                                    </button>
                                </li>
                            );
                        })}
                        {/* trailing "type your own" entry (design fig.3) */}
                        <li>
                            <button
                                type="button"
                                disabled={disabled || submitted}
                                onClick={() => handleSelect(q, CUSTOM_KEY)}
                                className={cn(
                                    'flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors',
                                    customSelected || !q.options.length
                                        ? 'border-blue-400 bg-blue-50 text-blue-700'
                                        : 'border-gray-200 text-gray-700 hover:border-blue-200 hover:bg-gray-50',
                                )}
                            >
                                <span className="flex-1">
                                    {q.options.length + 1}. {localize('com_linsight_clarify_custom')}
                                </span>
                            </button>
                        </li>
                    </ul>
                    {(customSelected || !q.options.length) && (
                        <Textarea
                            value={customText[q.id] || ''}
                            disabled={disabled || submitted}
                            rows={2}
                            maxLength={10000}
                            placeholder={localize('com_linsight_clarify_input_placeholder')}
                            onChange={(e) => {
                                setCustomText((prev) => ({ ...prev, [q.id]: e.target.value }));
                                if (!customSelected) handleSelect(q, CUSTOM_KEY);
                            }}
                            className="mt-2 resize-none text-sm"
                        />
                    )}
                </div>
            ) : (
                /* defensive fallback: nothing parseable -> plain textarea */
                <Textarea
                    value={freeText}
                    disabled={disabled || submitted}
                    rows={3}
                    maxLength={10000}
                    placeholder={localize('com_linsight_clarify_input_placeholder')}
                    onChange={(e) => setFreeText(e.target.value)}
                    className="mt-3 resize-none text-sm"
                />
            )}

            {/* footer: confirm (when answered) + skip */}
            <div className="mt-3 flex items-center justify-end gap-3">
                {hasAnswer && (
                    <Button size="sm" className="h-7 px-4" disabled={disabled || submitted} onClick={handleConfirm}>
                        {page < questions.length - 1
                            ? localize('com_linsight_clarify_next')
                            : localize('com_linsight_clarify_submit')}
                    </Button>
                )}
                <button
                    type="button"
                    disabled={disabled || submitted}
                    onClick={handleSkipCurrent}
                    className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50"
                >
                    {localize('com_linsight_clarify_skip')}
                    <ArrowRight size={12} />
                </button>
            </div>
        </div>
    );
}
