/**
 * F035 Track H (P3): intent-clarification / follow-up card (spec §2,
 * user_input event). One question per page (‹ 1/N ›): single-select /
 * multi-select / free text, with a trailing "type your own" option. Bottom
 * right "skip" skips the current question; top-right × skips the rest and
 * submits whatever was collected. All answers are merged into one structured
 * text and submitted through the existing user-input API in a single shot.
 * Unparseable payloads degrade to a plain textarea (legacy UserInput shape).
 */
import { ArrowRight, Check, ChevronLeft, ChevronRight, CornerDownLeft, X } from 'lucide-react';
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

// Split option text like "Option Title (Option Description)" into two parts
const parseOption = (text: string) => {
    const match = text.match(/^([^(]+)\s*(\([^)]+\))$/);
    if (match) {
        return {
            title: match[1].trim(),
            desc: match[2].trim(),
        };
    }
    return { title: text, desc: '' };
};

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
        // multi-select: toggle and stay on the page (confirm button submits).
        if (q.multiple) {
            setAnswers((prev) => {
                const current = prev[q.id] || [];
                const next = current.includes(option)
                    ? current.filter((o) => o !== option)
                    : [...current, option];
                return { ...prev, [q.id]: next };
            });
            return;
        }
        // single-select (design fig.1 — no confirm button, only "skip"):
        // picking a real option advances immediately; picking the custom entry
        // just opens the inline input and waits for confirm.
        const next = { ...answers, [q.id]: [option] };
        setAnswers(next);
        if (option !== CUSTOM_KEY) goNextOrSubmit(next);
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
        <div
            className="my-3 w-full rounded-2xl border border-[#EEF2F6] bg-white p-6 shadow-[0_4px_20px_rgba(0,0,0,0.03)]"
            style={{
                backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'5\' height=\'5\'%3E%3Ccircle cx=\'0.5\' cy=\'0.5\' r=\'0.5\' fill=\'%23EAEEFF\'/%3E%3C/svg%3E")',
                backgroundSize: '5px 5px',
            }}
        >
            {/* Header: Guide text + Close button */}
            <div className="flex items-center justify-between pb-1">
                <p className="text-[16px] font-semibold text-[#212121]">
                    {request.callReason || localize('com_linsight_clarify_title')}
                </p>
                <button
                    type="button"
                    onClick={handleClose}
                    className="shrink-0 rounded-full p-1 text-[#8C8C8C] hover:bg-gray-100 transition-colors"
                    aria-label="close"
                >
                    <X size={16} />
                </button>
            </div>

            {/* Body: Current question */}
            {q ? (
                <div className="mt-4">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <span className="text-[14px] font-bold text-[#1A1A1A]">{q.question}</span>
                            {/* Single/multi badge only makes sense when there are
                                options; a free-text-only question is neither. */}
                            {q.options.length > 0 && (
                                <span className="text-[14px] text-[#8C8C8C] select-none">
                                    {q.multiple
                                        ? localize('com_linsight_clarify_multi')
                                        : localize('com_linsight_clarify_single')}
                                </span>
                            )}
                        </div>
                        {questions.length > 1 && (
                            <div className="flex items-center gap-2 text-sm text-[#8C8C8C] select-none">
                                <button
                                    type="button"
                                    disabled={page === 0}
                                    onClick={() => setPage(page - 1)}
                                    className="rounded-full p-1 hover:bg-gray-100/80 disabled:opacity-30 transition-colors"
                                >
                                    <ChevronLeft size={16} />
                                </button>
                                <span className="font-medium">
                                    {page + 1}/{questions.length}
                                </span>
                                <button
                                    type="button"
                                    disabled={page === questions.length - 1}
                                    onClick={() => setPage(page + 1)}
                                    className="rounded-full p-1 hover:bg-gray-100/80 disabled:opacity-30 transition-colors"
                                >
                                    <ChevronRight size={16} />
                                </button>
                            </div>
                        )}
                    </div>
                    <ul className="mt-4 space-y-3">
                        {q.options.map((option, i) => {
                            const active = selected.includes(option);
                            const { title: optTitle, desc: optDesc } = parseOption(option);
                            return (
                                <li key={i}>
                                    <button
                                        type="button"
                                        disabled={disabled || submitted}
                                        onClick={() => handleSelect(q, option)}
                                        className={cn(
                                            'flex w-full items-start gap-2 rounded-xl px-4 py-2.5 text-left text-sm transition-all duration-200 select-none border-0',
                                            active
                                                ? 'bg-[#EDF2FF] text-[#335CFF] font-medium shadow-[0_2px_8px_rgba(51,92,255,0.08)]'
                                                : 'text-[#1A1A1A] hover:bg-gray-50/80',
                                        )}
                                    >
                                        <span className="shrink-0 font-medium text-[#8C8C8C]">{i + 1}.</span>
                                        <div className="flex-1 min-w-0">
                                            <span className={cn(active ? 'text-[#335CFF]' : 'text-[#1A1A1A]')}>{optTitle}</span>
                                            {optDesc && (
                                                <span className={cn('ml-1 text-[13px] font-normal', active ? 'text-[#335CFF]/80' : 'text-[#8C8C8C]')}>
                                                    {optDesc}
                                                </span>
                                            )}
                                        </div>
                                        {active && <Check size={16} className="shrink-0 text-[#335CFF] self-center" />}
                                    </button>
                                </li>
                            );
                        })}
                        {/* Trailing "type your own" entry: inline input */}
                        <li>
                            <div
                                className="flex items-center gap-2 rounded-xl bg-[#F5F7FA] px-4 py-2.5 transition-all duration-200"
                            >
                                <span className="shrink-0 text-sm font-medium text-[#8C8C8C]">
                                    {q.options.length + 1}.
                                </span>
                                <input
                                    type="text"
                                    disabled={disabled || submitted}
                                    value={customText[q.id] || ''}
                                    placeholder={localize('com_linsight_clarify_custom')}
                                    onFocus={() => !customSelected && handleSelect(q, CUSTOM_KEY)}
                                    onChange={(e) => {
                                        setCustomText((prev) => ({ ...prev, [q.id]: e.target.value }));
                                        if (!customSelected) handleSelect(q, CUSTOM_KEY);
                                    }}
                                    onKeyDown={(e) => {
                                        // Enter confirms the custom answer and advances
                                        // (single-select only; multi-select uses the footer button).
                                        if (e.key === 'Enter' && !q.multiple && customText[q.id]?.trim()) {
                                            e.preventDefault();
                                            handleConfirm();
                                        }
                                    }}
                                    className={cn(
                                        'flex-1 bg-transparent text-sm outline-none placeholder:text-[#8C8C8C]',
                                        customSelected ? 'text-[#1A1A1A] font-medium' : 'text-[#1A1A1A]',
                                    )}
                                />
                                {!q.multiple && customSelected && customText[q.id]?.trim() && (
                                    <button
                                        type="button"
                                        disabled={disabled || submitted}
                                        onClick={handleConfirm}
                                        className="flex shrink-0 items-center gap-1 text-sm font-medium text-[#1A1A1A] hover:text-[#335CFF] disabled:opacity-50 transition-colors"
                                    >
                                        {localize('com_linsight_clarify_submit')}
                                        <CornerDownLeft size={14} className="shrink-0" />
                                    </button>
                                )}
                            </div>
                        </li>
                    </ul>
                </div>
            ) : (
                /* Defensive fallback: nothing parseable -> plain textarea */
                <Textarea
                    value={freeText}
                    disabled={disabled || submitted}
                    rows={4}
                    maxLength={10000}
                    placeholder={localize('com_linsight_clarify_input_placeholder')}
                    onChange={(e) => setFreeText(e.target.value)}
                    className="mt-4 resize-none text-sm rounded-xl border-none shadow-none bg-[#F5F7FA] placeholder:text-[#8C8C8C] focus-visible:ring-0 focus-visible:outline-none"
                />
            )}

            {/* Footer: Confirm (when answered) + Skip */}
            <div className="mt-6 flex items-center justify-end gap-4">
                {hasAnswer && (q?.multiple || !q) && (
                    <Button
                        size="sm"
                        disabled={disabled || submitted}
                        onClick={handleConfirm}
                        className="h-8 rounded-lg bg-[#335CFF] text-white hover:bg-[#1E4DFF] px-4 text-xs font-semibold shadow-[0_2px_8px_rgba(51,92,255,0.2)] transition-all duration-200"
                    >
                        {page < questions.length - 1
                            ? localize('com_linsight_clarify_next')
                            : localize('com_linsight_clarify_submit')}
                    </Button>
                )}
                <button
                    type="button"
                    disabled={disabled || submitted}
                    onClick={handleSkipCurrent}
                    className="flex items-center gap-1 text-sm font-medium text-[#1A1A1A] hover:text-[#335CFF] disabled:opacity-50 transition-colors"
                >
                    {localize('com_linsight_clarify_skip')}
                    <ArrowRight size={14} className="ml-1 shrink-0" />
                </button>
            </div>
        </div>
    );
}
