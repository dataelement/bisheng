import { millisecondsInDay, millisecondsInHour, millisecondsInMinute } from 'date-fns/constants';
import { useLocalize } from '~/hooks';

// Use the same fixed elapsed-time units as the Desktop conversation sidebar.
const AGE_UNITS = [
  { unit: 'years', duration: 365 * millisecondsInDay },
  { unit: 'months', duration: 30 * millisecondsInDay },
  { unit: 'days', duration: millisecondsInDay },
  { unit: 'hours', duration: millisecondsInHour },
  { unit: 'minutes', duration: millisecondsInMinute },
] as const;

interface ConversationHistoryDateProps {
  updatedAt?: string | null;
  createdAt?: string | null;
  className: string;
}

export function ConversationHistoryDate({ updatedAt, createdAt, className }: ConversationHistoryDateProps) {
  const localize = useLocalize();
  const timestamp = Date.parse(updatedAt || createdAt || '');
  if (!Number.isFinite(timestamp)) return null;

  const elapsed = Date.now() - timestamp;
  const age = AGE_UNITS.find(({ duration }) => elapsed >= duration);
  const label = age
    ? localize(`com_workbench_sidebar.conversation_age.${age.unit}`, { n: Math.floor(elapsed / age.duration) })
    : localize('com_workbench_sidebar.conversation_age.now');

  return (
    <time className={className} dateTime={new Date(timestamp).toISOString()}>
      {label}
    </time>
  );
}
