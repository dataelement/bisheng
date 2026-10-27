import { useMemo } from 'react';
interface SuggestedQuestionsProps {
  questions: readonly string[];
  canExecute: boolean;
  onSelect: (question: string) => void;
}
/** Existing client question chips, rendered in the scrollable message flow. */
export function SuggestedQuestions({ questions, canExecute, onSelect }: SuggestedQuestionsProps) {
  const words = useMemo(() => {
    const candidates = [...new Set(questions.filter(question => question.trim()))];
    if (candidates.length <= 3) return candidates;
    const selected: string[] = [];
    while (selected.length < 3) {
      const index = Math.floor(Math.random() * candidates.length);
      selected.push(candidates.splice(index, 1)[0]);
    }
    return selected;
  }, [questions]);
  if (!canExecute || !words.length) return null;
  return <div className="space-y-2 mt-2 pl-12">
    {words.map(word => <p key={word} role="button" tabIndex={0}
      className="text-xs border w-fit p-3 py-1 rounded-md text-[#1f2937cc] dark:text-text-2 cursor-pointer hover:bg-[#6e87ac33]"
      onClick={() => { if (canExecute) onSelect(word); }}
      onKeyDown={event => { if (canExecute && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onSelect(word); } }}>{word}</p>)}
  </div>;
}
