interface ConversationHistoryDateProps {
  updatedAt?: string | null;
  className: string;
}

export function ConversationHistoryDate({ updatedAt, className }: ConversationHistoryDateProps) {
  const date = new Date(updatedAt ?? '');
  if (!Number.isFinite(date.getTime())) return null;

  return (
    <time className={className} dateTime={date.toISOString()}>
      {date.toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' })}
    </time>
  );
}
